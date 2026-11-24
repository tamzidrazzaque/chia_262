/* boom_div_select: operand-range- and dependency-aware selection between the
   hardware divider and the multiply-high reciprocal sequence for division /
   remainder by a compile-time constant, for MegaBOOM (MegaBoomV3Config).

   Why a pass and not a cost: GCC's expand_divmod decides div vs mulh per site
   from ONE scalar cost (tune int_div, COSTS_N_INSNS units) that cannot depend
   on the dividend.  On MegaBOOM the divider is rocket MulDiv with
   divUnroll=1, divEarlyOut=true (one unit, not pipelined), whose latency
   depends on the operands:
       unit L = 1 + neg_in + N + neg_out          (fire -> resp, unit RTL)
       N = 3 + (msb(a) - msb(b))        when msb(a) >= msb(b), diff <= 62
       N = 65                           b == 0, diff == 63, msb(b) == msb(a)+1
       N = 67 - (msb(b) - msb(a))       when msb(a) < msb(b)  (6-bit wrap)
   so a SMALL quotient (msb(a) just above msb(b)) is fast, while a ZERO
   quotient with msb(a) < msb(b) (a < d, including a == 0) is the slowest
   case.  The reciprocal sequence costs a fixed latency dominated by the
   6-cycle mul issue-to-dependent-issue latency (pipelined, 1 per cycle).

   Per site the pass:
     1. queries the dividend range (ranger, context sensitive, + nonzero bits),
     2. computes the WORST-CASE hardware latency/occupancy over that range
        (formula above, magnitude intervals split at zero for signed types),
     3. builds the exact GCC expand_divmod reciprocal sequence (same
        choose_multiplier, pre/post shifts, add variant, sign fix) and
        computes its dataflow latency and uop count,
     4. classifies the use: LATENCY context if the result is on a loop-carried
        recurrence of the innermost loop (or the site is not in a loop),
        THROUGHPUT context otherwise (sums the worst-case occupancy of every
        hardware divide kept in the same loop body against the loop's
        estimated issue time),
     5. forces the decision:
          SEQ: rewrites the statement into the explicit sequence in GIMPLE
               (MULT_HIGHPART_EXPR for 64-bit, widened 64-bit multiply for
               32-bit), so expand cannot keep a div even when int_div is low;
          HW : replaces the constant divisor by an SSA name defined by an
               empty non-volatile asm ("=r" <- "0"(C)) placed in the
               preheader of the outermost enclosing loop (or before the
               statement), so expand cannot see a constant and cannot
               expand it into a sequence even when int_div is high; RTL
               passes cannot see through the asm either.

   Plugin args (defaults from rtl-model/ + range-aware-div measurements):
     core-lat=N   core issue->dependent-issue cycles added to unit L (3)
     core-occ=N   divider occupancy (div issue -> next div issue) added to unit L (3,
                  fit on [verilator-megaboom-rtl] rdgrid ind kernels, see log)
     mul-lat=N    mul/mulh issue->dependent-issue latency (6)
     alu-lat=N    ALU latency (1)
     issue=N      integer issue width for the uop-cost (4)
     margin=N     HW must beat SEQ by more than N cycles (0)
     rob=N        ROB entries; latency hidden off-recurrence <= rob/issue (128)
     mode=auto|hw|seq|off   force all eligible sites (testing), off = report only
     verbose=1    decisions on stderr (one line per site, census format)
   Dump: -fdump-tree-boom_div_select.  */

#include "gcc-plugin.h"
#include "plugin-version.h"
#include "tree.h"
#include "gimple.h"
#include "gimple-iterator.h"
#include "gimple-pretty-print.h"
#include "tree-pass.h"
#include "context.h"
#include "ssa.h"
#include "diagnostic.h"
#include "cfgloop.h"
#include "fold-const.h"
#include "stringpool.h"
#include "value-range.h"
#include "value-query.h"
#include "gimple-range.h"
#include "tree-cfg.h"
#include "expmed.h"
#include "predict.h"
#include "stor-layout.h"
#include "sreal.h"

#include <vector>
#include <set>
#include <map>
#include <string>
#include <algorithm>

int plugin_is_GPL_compatible;

static int core_lat = 3, core_occ = 3, mul_lat = 6, alu_lat = 1, issue_w = 4, margin = 0, rob_entries = 128;
static int verbose = 0;
enum mode_t_ { M_AUTO, M_HW, M_SEQ, M_OFF };
static mode_t_ mode = M_AUTO;
static unsigned long long n_sites, n_hw, n_seq, n_skip;

/* ------------------------------------------------------------------ */
/* Divider model (validated vs unit RTL, rtl-model/boomhw/muldiv_model.py). */

static int msb64(unsigned long long v) { return v ? 63 - __builtin_clzll(v) : 0; }

static int div_N(int da, int v) {
  int diff = (da - v) & 63;
  int e = 63 - diff;
  return e < 1 ? 65 : 66 - e;
}

/* Worst/best unit N over magnitudes [lo, hi] for divisor magnitude msb v.  */
static void n_over(unsigned long long lo, unsigned long long hi, int v, int *worst, int *best) {
  int a0 = msb64(lo), a1 = msb64(hi);
  for (int m = a0; m <= a1; m++) {
    int n = div_N(m, v);
    *worst = std::max(*worst, n);
    *best = std::min(*best, n);
  }
}

struct hwcost {
  int worst = 0, best = 1000;  /* unit cycles L */
  bool zero_quot = false;      /* range admits msb(a) < msb(d) (slow wrap) */
  bool unknown = false;        /* varying: full width assumed */
};

/* Magnitude pieces of a (sub)range for the divider.  neg: operand negative. */
static void add_piece(hwcost &h, unsigned long long lo, unsigned long long hi, bool neg, bool sgn,
                      bool d_neg, bool is_mod, int v) {
  int w = 0, b = 1000;
  n_over(lo, hi, v, &w, &b);
  int neg_in = sgn && (neg || d_neg) ? 1 : 0;
  int neg_out = sgn && (is_mod ? neg : (neg != d_neg)) ? 1 : 0;
  h.worst = std::max(h.worst, 1 + neg_in + w + neg_out);
  h.best = std::min(h.best, 1 + neg_in + b + neg_out);
  if (msb64(lo) < v)
    h.zero_quot = true;
}

/* ------------------------------------------------------------------ */
/* Sequence builder: mirrors expmed.cc expand_divmod (GCC 15.1) for
   TRUNC_DIV/TRUNC_MOD by a constant, non power of two.  Values carry a
   dataflow ready time for the latency estimate.  */

struct val { tree t; int ready; };

struct seqb {
  gimple_seq seq = NULL;
  int uops = 0, muls = 0;
  bool emit_ir;  /* false: only cost, no IL */
  val op(enum tree_code code, tree type, val a, val b, int lat) {
    val r;
    r.ready = std::max(a.ready, b.ready) + lat;
    uops++;
    if (lat == mul_lat) muls++;
    if (emit_ir) {
      r.t = make_ssa_name(type);
      gimple_seq_add_stmt(&seq, gimple_build_assign(r.t, code, a.t, b.t));
    } else
      r.t = NULL_TREE;
    return r;
  }
  val op1(enum tree_code code, tree type, val a, int lat) {
    val r;
    r.ready = a.ready + lat;
    if (code != NOP_EXPR) uops++;
    if (emit_ir) {
      r.t = make_ssa_name(type);
      gimple_seq_add_stmt(&seq, gimple_build_assign(r.t, code, a.t));
    } else
      r.t = NULL_TREE;
    return r;
  }
  val cst(tree type, unsigned long long v) {
    val r;
    r.ready = 0;
    r.t = emit_ir ? build_int_cst_type(type, (HOST_WIDE_INT)v) : NULL_TREE;
    return r;
  }
  val shift(enum tree_code code, tree type, val a, int s) {
    if (s == 0) return a;
    val c; c.ready = 0;
    c.t = emit_ir ? build_int_cst(unsigned_type_node, s) : NULL_TREE;
    return op(code, type, a, c, alu_lat);
  }
  val conv(tree type, val a, int lat) {
    if (emit_ir && types_compatible_p(type, TREE_TYPE(a.t))) return a;
    return op1(NOP_EXPR, type, a, lat);
  }
};

static tree u64t, s64t;

/* High part of x * ml in TYPE (precision 32 or 64).  32-bit uses a widened
   64-bit multiply (what RV64 expand does for SImode highpart).  */
static val mulhigh(seqb &B, tree type, val x, unsigned long long ml, bool uns) {
  unsigned prec = TYPE_PRECISION(type);
  if (prec == 64) {
    val m = B.cst(type, ml);
    return B.op(MULT_HIGHPART_EXPR, type, x, m, mul_lat);
  }
  tree wt = uns ? u64t : s64t;
  /* sign/zero extension of a 32-bit value: free for a sign-extended signed
     int on RV64; an unsigned int needs a zero extension (slli+srli: 2). */
  val xw = B.conv(wt, x, uns ? 2 * alu_lat : 0);
  if (uns) B.uops += 2;
  unsigned long long mlw = uns ? (ml & 0xffffffffULL)
                               : (unsigned long long)(long long)(int)(unsigned)ml;
  val m = B.cst(wt, mlw);
  val p = B.op(MULT_EXPR, wt, xw, m, mul_lat);
  val h = B.shift(RSHIFT_EXPR, wt, p, 32);
  return B.conv(type, h, 0);
}

/* Returns false if the constant is not handled (power of two etc.).  */
/* NONNEG: the (signed) dividend is known >= 0, so the sign correction
   x >> (prec-1) is 0 and is omitted (GCC's expand keeps it).  */
static bool build_seq(seqb &B, tree type, val x, HOST_WIDE_INT dval, bool is_mod, val *res,
                      bool nonneg = false) {
  unsigned prec = TYPE_PRECISION(type);
  bool uns = TYPE_UNSIGNED(type);
  int size = prec;
  val q;
  if (uns) {
    unsigned long long d = (unsigned long long)dval;
    if (prec == 32) d &= 0xffffffffULL;
    if (d <= 1 || (d & (d - 1)) == 0) return false;
    if (d >= (1ULL << (size - 1))) return false;  /* GCC uses scc */
    unsigned HOST_WIDE_INT ml;
    int post, pre = 0;
    unsigned long long mh = choose_multiplier(d, size, size, &ml, &post);
    if (mh != 0 && (d & 1) == 0) {
      pre = __builtin_ctzll(d);
      mh = choose_multiplier(d >> pre, size, size - pre, &ml, &post);
      gcc_assert(!mh);
    }
    if (mh != 0) {
      val t1 = mulhigh(B, type, x, ml, true);
      val t2 = B.op(MINUS_EXPR, type, x, t1, alu_lat);
      val t3 = B.shift(RSHIFT_EXPR, type, t2, 1);
      val t4 = B.op(PLUS_EXPR, type, t1, t3, alu_lat);
      q = B.shift(RSHIFT_EXPR, type, t4, post - 1);
    } else {
      val t1 = B.shift(RSHIFT_EXPR, type, x, pre);
      val t2 = mulhigh(B, type, t1, ml, true);
      q = B.shift(RSHIFT_EXPR, type, t2, post);
    }
    if (is_mod) {
      val dc = B.cst(type, d);
      val p = B.op(MULT_EXPR, type, q, dc, mul_lat);
      q = B.op(MINUS_EXPR, type, x, p, alu_lat);
    }
    *res = q;
    return true;
  }
  long long d = (long long)dval;
  if (prec == 32) d = (int)d;
  unsigned long long abs_d = d >= 0 ? (unsigned long long)d : -(unsigned long long)d;
  if (abs_d <= 1 || (abs_d & (abs_d - 1)) == 0) return false;
  if (is_mod && d < 0) d = (long long)abs_d;
  unsigned HOST_WIDE_INT ml;
  int post;
  choose_multiplier(abs_d, size, size - 1, &ml, &post);
  val t3s, t2s;
  if (ml < (1ULL << (size - 1))) {
    val t1 = mulhigh(B, type, x, ml, false);
    t2s = B.shift(RSHIFT_EXPR, type, t1, post);
  } else {
    ml |= (~0ULL) << (size - 1);
    val t1 = mulhigh(B, type, x, ml, false);
    val t2 = B.op(PLUS_EXPR, type, t1, x, alu_lat);
    t2s = B.shift(RSHIFT_EXPR, type, t2, post);
  }
  if (!nonneg) {
#ifdef BOOM_DIV_SELECT_MUTANT
    t3s = B.shift(RSHIFT_EXPR, type, x, size - 2);  /* deliberate bug: harness sensitivity test */
#else
    t3s = B.shift(RSHIFT_EXPR, type, x, size - 1);
#endif
  }
  /* No signed overflow is possible in any of these operations: |t1| and
     |t1 + x| are <= |x|, t3s is 0 or -1, and |q * d| <= |x|.  */
  if (nonneg) {
    q = d < 0 ? B.op1(NEGATE_EXPR, type, t2s, alu_lat) : t2s;
  } else if (d < 0)
    q = B.op(MINUS_EXPR, type, t3s, t2s, alu_lat);
  else
    q = B.op(MINUS_EXPR, type, t2s, t3s, alu_lat);
  if (is_mod) {
    val dc = B.cst(type, abs_d);
    val p = B.op(MULT_EXPR, type, q, dc, mul_lat);
    q = B.op(MINUS_EXPR, type, x, p, alu_lat);
  }
  *res = q;
  return true;
}

/* ------------------------------------------------------------------ */
/* Dependency analysis: is the statement on a recurrence of its innermost
   loop?  Backward SSA slice of the dividend inside the loop reaching a
   header PHI whose latch argument's backward slice contains the stmt.  */

static void bslice(tree t, class loop *L, std::set<gimple *> &seen, std::vector<gphi *> &hdr_phis,
                   int budget) {
  std::vector<tree> work{t};
  while (!work.empty() && budget-- > 0) {
    tree x = work.back();
    work.pop_back();
    if (TREE_CODE(x) != SSA_NAME || SSA_NAME_IS_DEFAULT_DEF(x)) continue;
    gimple *def = SSA_NAME_DEF_STMT(x);
    if (!def || !gimple_bb(def) || !flow_bb_inside_loop_p(L, gimple_bb(def))) continue;
    if (!seen.insert(def).second) continue;
    if (gphi *p = dyn_cast<gphi *>(def)) {
      if (gimple_bb(p) == L->header) {
        hdr_phis.push_back(p);
        continue;  /* do not cross the back edge here */
      }
      for (unsigned i = 0; i < gimple_phi_num_args(p); i++) work.push_back(gimple_phi_arg_def(p, i));
      continue;
    }
    ssa_op_iter it;
    tree use;
    FOR_EACH_SSA_TREE_OPERAND(use, def, it, SSA_OP_USE) work.push_back(use);
  }
}

static bool on_recurrence(gimple *stmt, class loop *L) {
  std::set<gimple *> seen;
  std::vector<gphi *> phis;
  bslice(gimple_assign_rhs1(stmt), L, seen, phis, 4000);
  edge latch = loop_latch_edge(L);
  for (gphi *p : phis) {
    std::set<gimple *> s2;
    std::vector<gphi *> ph2;
    bslice(PHI_ARG_DEF_FROM_EDGE(p, latch), L, s2, ph2, 4000);
    if (s2.count(stmt)) return true;
  }
  return false;
}

/* Expected non-trivial statements per iteration of L: blocks whose
   innermost loop is L, weighted by their frequency relative to the header
   (inner loops are ignored, which under-estimates the iteration time, i.e.
   errs against hiding a divide).  */
static double loop_iter_insns(class loop *L) {
  basic_block *bbs = get_loop_body(L);
  double n = 0;
  for (unsigned i = 0; i < L->num_nodes; i++) {
    basic_block bb = bbs[i];
    if (bb->loop_father != L) continue;
    bool ok = true;
    sreal f = bb->count.to_sreal_scale(L->header->count, &ok);
    double w = ok ? f.to_double() : 1.0;
    if (w > 1.0) w = 1.0;
    int k = 0;
    for (gimple_stmt_iterator gsi = gsi_start_bb(bb); !gsi_end_p(gsi); gsi_next(&gsi)) {
      gimple *s = gsi_stmt(gsi);
      if (is_gimple_debug(s) || gimple_code(s) == GIMPLE_LABEL || gimple_code(s) == GIMPLE_NOP) continue;
      if (is_gimple_assign(s) && gimple_assign_single_p(s) && !gimple_vuse(s) &&
          TREE_CODE(gimple_assign_rhs1(s)) == SSA_NAME)
        continue;  /* copies */
      k++;
    }
    n += w * k;
  }
  free(bbs);
  return n;
}

/* ------------------------------------------------------------------ */

struct site {
  gimple *stmt;
  tree type;    /* work type: 32- or 64-bit (narrow types are widened) */
  tree otype;   /* statement type */
  HOST_WIDE_INT d;
  bool is_mod, uns;
  hwcost hw;
  int seq_lat, seq_uops, seq_muls;
  class loop *loop;   /* innermost real loop or NULL */
  bool recur;
  bool decide_hw = false;
  bool touch = true;
  bool x_nonneg = false;   /* signed type, dividend known >= 0 */
  bool x_lt_half = false;  /* unsigned type, dividend known < 2^(prec-1) */
  bool alt = false;        /* SEQ uses the other signedness (as expand_expr does) */
  std::string why, range_s;
};

static const char *tname(tree type) {
  bool u = TYPE_UNSIGNED(type);
  return TYPE_PRECISION(type) == 64 ? (u ? "u64" : "s64") : (u ? "u32" : "s32");
}

static void range_cost(function *fun, site &s) {
  tree x = gimple_assign_rhs1(s.stmt);
  unsigned prec = TYPE_PRECISION(s.type);
  bool sgn = !s.uns;
  long long d = prec == 32 ? (s.uns ? (long long)(unsigned)s.d : (long long)(int)s.d) : (long long)s.d;
  bool d_neg = sgn && d < 0;
  unsigned long long dm = d_neg ? -(unsigned long long)d : (unsigned long long)d;
  if (prec == 32) dm &= 0xffffffffULL;
  int v = msb64(dm);
  int_range_max r;
  bool have = TREE_CODE(x) == SSA_NAME && get_range_query(fun)->range_of_expr(r, x, s.stmt) &&
              !r.undefined_p() && !r.varying_p();
  unsigned long long full = prec == 64 ? ~0ULL : 0xffffffffULL;
  char buf[256];
  if (have) {
    if (sgn) s.x_nonneg = !wi::neg_p(r.lower_bound(0), SIGNED);
    else {
      unsigned long long ub = std::min((unsigned long long)r.upper_bound(r.num_pairs() - 1).to_uhwi(),
                                       (unsigned long long)(r.get_nonzero_bits().to_uhwi() & full));
      s.x_lt_half = ub < (1ULL << (prec - 1));
    }
  } else if (TYPE_PRECISION(s.otype) < prec) {
    s.x_lt_half = s.uns;  /* zero-extended narrow unsigned value */
    s.x_nonneg = false;
  }
  if (!have) {
    /* varying in the statement type: full range of THAT precision (an
       unsigned char dividend is [0,255], not full 32-bit).  */
    unsigned op_ = TYPE_PRECISION(s.otype);
    unsigned long long ofull = op_ >= 64 ? ~0ULL : ((1ULL << op_) - 1);
    s.hw.unknown = true;
    if (sgn) {
      add_piece(s.hw, 0, ofull >> 1, false, true, d_neg, s.is_mod, v);
      add_piece(s.hw, 1, (ofull >> 1) + 1, true, true, d_neg, s.is_mod, v);
    } else
      add_piece(s.hw, 0, ofull, false, false, d_neg, s.is_mod, v);
    snprintf(buf, sizeof buf, "varying(%u-bit)", op_);
    s.range_s = buf;
    return;
  }
  wide_int nz = r.get_nonzero_bits();
  unsigned long long nzm = nz.to_uhwi() & full;
  std::string rs;
  for (unsigned i = 0; i < r.num_pairs(); i++) {
    wide_int lo = r.lower_bound(i), hi = r.upper_bound(i);
    if (sgn) {
      long long l = lo.to_shwi(), h = hi.to_shwi();
      snprintf(buf, sizeof buf, "%s[%lld,%lld]", i ? "U" : "", l, h);
      rs += buf;
      if (h >= 0) {
        unsigned long long pl = l < 0 ? 0 : (unsigned long long)l;
        unsigned long long ph = (unsigned long long)h;
        ph = std::min(ph, nzm);  /* nonneg part bounded by the nonzero bits */
        if (ph < pl) ph = pl;
        add_piece(s.hw, pl, ph, false, true, d_neg, s.is_mod, v);
      }
      /* A negative value has the sign bit set: impossible if the
         nonzero-bits mask clears it (ranger keeps the mask separately
         from the pairs, e.g. [-2^31,-10]U[10,2^31-1] with nz=0xf).  */
      bool neg_ok = (nzm >> (TYPE_PRECISION(s.otype) - 1)) & 1;
      if (l < 0 && neg_ok) {
        long long nh = std::min(h, -1LL);
        unsigned long long ml_ = -(unsigned long long)nh;  /* smallest magnitude */
        unsigned long long mh_ = -(unsigned long long)l;   /* largest magnitude */
        add_piece(s.hw, ml_, mh_, true, true, d_neg, s.is_mod, v);
      }
    } else {
      unsigned long long l = lo.to_uhwi(), h = hi.to_uhwi();
      snprintf(buf, sizeof buf, "%s[%llu,%llu]", i ? "U" : "", l, h);
      rs += buf;
      h = std::min(h, nzm);
      if (h < l) h = l;
      add_piece(s.hw, l, h, false, false, false, s.is_mod, v);
    }
  }
  snprintf(buf, sizeof buf, " nz=0x%llx", nzm);
  s.range_s = rs + buf;
}

static gimple *opaque_def(tree t_out, tree cst) {
  vec<tree, va_gc> *ins = NULL, *outs = NULL;
  tree in = build_tree_list(build_tree_list(NULL_TREE, build_string(2, "0")), cst);
  tree out = build_tree_list(build_tree_list(NULL_TREE, build_string(3, "=r")), t_out);
  vec_safe_push(ins, in);
  vec_safe_push(outs, out);
  gasm *a = gimple_build_asm_vec("", ins, outs, NULL, NULL);
  gimple_asm_set_volatile(a, false);
  SSA_NAME_DEF_STMT(t_out) = a;
  return a;
}

static void note(FILE *f, const char *fmt, ...) ATTRIBUTE_PRINTF_2;
static void note(FILE *f, const char *fmt, ...) {
  va_list ap;
  if (f) { va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap); }
  if (verbose) { va_start(ap, fmt); vfprintf(stderr, fmt, ap); va_end(ap); }
}

static unsigned int run(function *fun) {
  u64t = long_long_unsigned_type_node;
  s64t = long_long_integer_type_node;
  loop_optimizer_init(LOOPS_NORMAL);
  enable_ranger(fun);
  const char *fname = function_name(fun);
  std::vector<site> sites;
  basic_block bb;
  FOR_EACH_BB_FN(bb, fun) {
    for (gimple_stmt_iterator gsi = gsi_start_bb(bb); !gsi_end_p(gsi); gsi_next(&gsi)) {
      gimple *stmt = gsi_stmt(gsi);
      if (!is_gimple_assign(stmt)) continue;
      enum tree_code code = gimple_assign_rhs_code(stmt);
      if (code != TRUNC_DIV_EXPR && code != TRUNC_MOD_EXPR) continue;
      tree type = TREE_TYPE(gimple_assign_lhs(stmt));
      tree d = gimple_assign_rhs2(stmt);
      if (!INTEGRAL_TYPE_P(type) || TREE_CODE(d) != INTEGER_CST) continue;
      unsigned prec = TYPE_PRECISION(type);
      location_t loc = gimple_location(stmt);
      expanded_location xl = expand_location(loc);
      tree otype = type;
      if (prec < 32 && prec >= 2 && (TYPE_MODE(type) == QImode || TYPE_MODE(type) == HImode)) {
        /* expand widens QI/HI division to SImode (divw/divuw); model and
           rewrite in the 32-bit type of the same signedness.  */
        type = TYPE_UNSIGNED(type) ? unsigned_type_node : integer_type_node;
        prec = 32;
      }
      if (!((prec == 64 && TYPE_MODE(type) == DImode) || (prec == 32 && TYPE_MODE(type) == SImode))) {
        note(dump_file, "SITE %s %s:%d prec=%u skip=narrow-or-wide\n", fname, xl.file ? xl.file : "?", xl.line, prec);
        n_skip++;
        continue;
      }
      if (TREE_CODE(gimple_assign_rhs1(stmt)) != SSA_NAME) continue;
      site s;
      s.stmt = stmt;
      s.type = type;
      s.otype = otype;
      s.d = TYPE_UNSIGNED(type) ? (HOST_WIDE_INT)TREE_INT_CST_LOW(d) : tree_to_shwi(d);
      s.is_mod = code == TRUNC_MOD_EXPR;
      s.uns = TYPE_UNSIGNED(type);
      range_cost(fun, s);
      seqb B;
      B.emit_ir = false;
      val x{NULL_TREE, 0}, r;
      if (!build_seq(B, type, x, s.d, s.is_mod, &r, !s.uns && s.x_nonneg)) {
        n_skip++;
        note(dump_file, "SITE %s %s:%d %s %s d=%lld skip=pow2-or-trivial\n", fname, xl.file ? xl.file : "?",
             xl.line, tname(type), s.is_mod ? "mod" : "div", (long long)s.d);
        continue;
      }
      s.seq_lat = r.ready;
      s.seq_uops = B.uops;
      s.seq_muls = B.muls;
      /* Known non-negative dividend: expand_expr tries both signednesses
         and keeps the cheaper sequence; do the same.  */
      if ((s.x_nonneg && s.d > 0) || s.x_lt_half) {
        tree at = s.uns ? (prec == 64 ? s64t : integer_type_node)
                        : (prec == 64 ? u64t : unsigned_type_node);
        seqb A;
        A.emit_ir = false;
        val ra;
        if (build_seq(A, at, x, s.d, s.is_mod, &ra, s.uns) &&
            (ra.ready < s.seq_lat || (ra.ready == s.seq_lat && A.uops < s.seq_uops))) {
          s.alt = true;
          s.seq_lat = ra.ready;
          s.seq_uops = A.uops;
          s.seq_muls = A.muls;
        }
      }
      class loop *l = bb->loop_father;
      s.loop = (l && loop_outer(l)) ? l : NULL;
      s.recur = s.loop && on_recurrence(stmt, s.loop);
      sites.push_back(s);
    }
  }

  /* Decisions.  Latency context first (independent per site); then
     throughput context per loop with the summed divider occupancy.  */
  std::map<class loop *, std::vector<site *>> thr;
  for (site &s : sites) {
    n_sites++;
    int hw_lat = s.hw.worst + core_lat;
    if (mode == M_HW) { s.decide_hw = true; s.why = "forced"; continue; }
    if (mode == M_SEQ) { s.decide_hw = false; s.why = "forced"; continue; }
    if (optimize_bb_for_size_p(gimple_bb(s.stmt))) {
      s.touch = false; s.why = "size: left to GCC";
      continue;
    }
    if (!s.loop || s.recur) {
      s.decide_hw = hw_lat + margin < s.seq_lat;
      s.why = s.recur ? "latency(recurrence)" : "latency(no loop)";
    } else
      thr[s.loop].push_back(&s);
  }
  for (auto &kv : thr) {
    class loop *L = kv.first;
    double iter = loop_iter_insns(L);
    /* A divide whose result is not on a recurrence is hidden only if
       (a) its latency fits in the window the ROB can cover while the rest of
           the iteration issues: rob/issue cycles at most (128/4 = 32 on
           MegaBOOM), else retirement stalls behind it, and
       (b) the summed divider occupancy of the hardware divides kept in this
           loop fits under the iteration's issue time (one unpipelined unit).
       Greedy over sites by worst-case occupancy.  SEQ costs uops/issue.  */
    std::vector<site *> v = kv.second;
    std::sort(v.begin(), v.end(), [](site *a, site *b) { return a->hw.worst < b->hw.worst; });
    int occ_sum = 0;
    for (site *s : v) {
      int occ = s->hw.worst + core_occ;
      int lat = s->hw.worst + core_lat;
      double others = (iter - 1) / issue_w;  /* issue cycles/iter without this div */
      bool hidden = lat + margin <= rob_entries / issue_w;
      bool fits = occ_sum + occ <= others;
      s->decide_hw = hidden && fits;
      if (s->decide_hw) occ_sum += occ;
      char b[160];
      snprintf(b, sizeof b, "throughput(iter_insns=%.1f hide_win=%d occ_sum=%d occ=%d%s%s)", iter,
               rob_entries / issue_w, occ_sum, occ, hidden ? "" : " lat>window", fits ? "" : " occ>iter");
      s->why = b;
    }
  }

  disable_ranger(fun);

  for (site &s : sites) {
    expanded_location xl = expand_location(gimple_location(s.stmt));
    note(dump_file,
         "SITE %s %s:%d %s%s %s d=%lld loop=%d depth=%d recur=%d range=%s zero_quot=%d "
         "hw_unit=[%d,%d] hw_lat_worst=%d seq_lat=%d seq_uops=%d%s -> %s (%s)\n",
         fname, xl.file ? xl.file : "?", xl.line, tname(s.type),
         TYPE_PRECISION(s.otype) < 32 ? (TYPE_PRECISION(s.otype) == 8 ? "(from8)" : "(from16)") : "", s.is_mod ? "mod" : "div", (long long)s.d,
         s.loop ? s.loop->num : -1, s.loop ? loop_depth(s.loop) : 0, s.recur, s.range_s.c_str(),
         s.hw.zero_quot, s.hw.best, s.hw.worst, s.hw.worst + core_lat, s.seq_lat, s.seq_uops,
         s.alt ? " seq_alt_sign=1" : "",
         !s.touch ? "KEEP" : s.decide_hw ? "HW" : "SEQ", s.why.c_str());
    if (mode == M_OFF || !s.touch) { n_skip += !s.touch; continue; }
    gimple_stmt_iterator gsi = gsi_for_stmt(s.stmt);
    if (s.decide_hw) {
      n_hw++;
      tree cst = gimple_assign_rhs2(s.stmt);
      tree t = make_ssa_name(s.otype);
      gimple *a = opaque_def(t, cst);
      /* preheader of the outermost loop containing the site */
      class loop *outer = s.loop;
      while (outer && loop_outer(outer) && loop_outer(loop_outer(outer))) outer = loop_outer(outer);
      if (outer)
        gsi_insert_on_edge_immediate(loop_preheader_edge(outer), a);
      else
        gsi_insert_before(&gsi, a, GSI_SAME_STMT);
      gimple_assign_set_rhs2(s.stmt, t);
      update_stmt(s.stmt);
    } else {
      n_seq++;
      seqb B;
      B.emit_ir = true;
      val x{gimple_assign_rhs1(s.stmt), 0}, r;
      tree wt = s.type;
      if (s.alt) {
        unsigned pr = TYPE_PRECISION(s.type);
        wt = s.uns ? (pr == 64 ? s64t : integer_type_node) : (pr == 64 ? u64t : unsigned_type_node);
      }
      x = B.conv(wt, x, 0);
      bool ok = build_seq(B, wt, x, s.d, s.is_mod, &r, !TYPE_UNSIGNED(wt) && (s.alt ? s.x_lt_half : s.x_nonneg));
      gcc_assert(ok);
      r = B.conv(s.otype, r, 0);
      gsi_insert_seq_before(&gsi, B.seq, GSI_SAME_STMT);
      gimple_assign_set_rhs_with_ops(&gsi, SSA_NAME, r.t);
      update_stmt(gsi_stmt(gsi));
    }
  }
  loop_optimizer_finalize();
  free_dominance_info(CDI_DOMINATORS);
  return 0;
}

namespace {
const pass_data pass_data_sel = {
    GIMPLE_PASS, "boom_div_select", OPTGROUP_NONE, TV_NONE,
    PROP_cfg | PROP_ssa, 0, 0, 0, TODO_update_ssa_only_virtuals};

class pass_sel : public gimple_opt_pass {
 public:
  pass_sel(gcc::context *ctxt) : gimple_opt_pass(pass_data_sel, ctxt) {}
  bool gate(function *) override { return optimize > 0; }
  unsigned int execute(function *fun) override { return run(fun); }
};
}  // namespace

static void finish(void *, void *) {
  if (verbose)
    fprintf(stderr, "boom_div_select: sites=%llu hw=%llu seq=%llu skipped=%llu\n", n_sites, n_hw, n_seq,
            n_skip);
}

int plugin_init(struct plugin_name_args *info, struct plugin_gcc_version *version) {
#ifdef BOOM_RELAX_VERSION
  /* For the novelty/ int_div-override build of the same GCC 15.1 sources
     (only riscv.cc differs; different pkgversion/configure args).  */
  if (strcmp(version->basever, gcc_version.basever)) return 1;
#else
  if (!plugin_default_version_check(version, &gcc_version)) return 1;
#endif
  for (int i = 0; i < info->argc; i++) {
    const char *k = info->argv[i].key;
    const char *v = info->argv[i].value ? info->argv[i].value : "1";
    if (!strcmp(k, "core-lat")) core_lat = atoi(v);
    else if (!strcmp(k, "core-occ")) core_occ = atoi(v);
    else if (!strcmp(k, "mul-lat")) mul_lat = atoi(v);
    else if (!strcmp(k, "alu-lat")) alu_lat = atoi(v);
    else if (!strcmp(k, "issue")) issue_w = atoi(v);
    else if (!strcmp(k, "margin")) margin = atoi(v);
    else if (!strcmp(k, "rob")) rob_entries = atoi(v);
    else if (!strcmp(k, "verbose")) verbose = atoi(v);
    else if (!strcmp(k, "mode"))
      mode = !strcmp(v, "hw") ? M_HW : !strcmp(v, "seq") ? M_SEQ : !strcmp(v, "off") ? M_OFF : M_AUTO;
    else
      warning(0, "boom_div_select: unknown argument %qs", k);
  }
  static register_pass_info rp;
  rp.pass = new pass_sel(g);
  rp.reference_pass_name = "optimized";
  rp.ref_pass_instance_number = 1;
  rp.pos_op = PASS_POS_INSERT_AFTER;
  register_callback(info->base_name, PLUGIN_PASS_MANAGER_SETUP, nullptr, &rp);
  register_callback(info->base_name, PLUGIN_FINISH, finish, nullptr);
  return 0;
}
