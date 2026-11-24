/* boom_invariant_div: loop-invariant runtime-divisor strength reduction.

   GCC replaces x / C and x % C (C a compile-time constant) by a multiply-high
   sequence, but never touches x / d when d is only known at run time, even
   when d is loop invariant.  On BOOM the divider is one iterative,
   unpipelined unit (rocket MulDiv, 1 bit/cycle, early out), while mulhu is a
   pipelined 3-cycle op.  This pass finds TRUNC_DIV_EXPR / TRUNC_MOD_EXPR
   inside a loop whose divisor SSA name is defined outside that loop, computes
   an exact reciprocal once in the loop preheader, and rewrites the in-loop
   operations as multiplies.

   Supported operand kinds and methods (all exact; see README/log for the
   arguments):
     U32  unsigned <=32-bit (narrower types are zero-extended):
            c' = 0xFFFFFFFFFFFFFFFF / d               (preheader, one divu)
            q  = mulhu(c', n + 1)                     (round-down + increment;
                 exact for all 1 <= d < 2^32 incl. d = 1 and powers of two,
                 proof in README: c' = 2^64/d - e with 0 < e <= 1)
            [u32-quot=mask: Lemire et al. 2019, c = c' + 1,
                 q = mulhu(c, n) + (n & -(d == 1))]
            r  = mulhu(c * n mod 2^64, d), c = c' + 1  (Lemire, Kaser, Kurz
                 2019 fastmod, F = 64; d == 1 gives c = 0, r = 0)
     S32  signed 32-bit: |n|, |d| (as 64-bit unsigned, so INT_MIN is fine),
          then the U32 method, then sign fix: q = (uq ^ s) - s with
          s = sign(n) ^ sign(d); r = (ur ^ sn) - sn.
     U64  unsigned 64-bit: Granlund-Montgomery 1994 (Fig. 4.1, round-up
          method with N+1-bit multiplier), valid for every 1 <= d < 2^64:
            l  = ceil(log2 d)
            m' = floor(2^64 * (2^l - d) / d) + 1     (128/64 divide, libcall)
            sh1 = min(l, 1), sh2 = max(l - 1, 0)
            t = mulhu(m', n); q = (t + ((n - t) >> sh1)) >> sh2
            r = n - q * d
     S64  signed 64-bit: abs/sign-fix around U64 (|INT64_MIN| = 2^63 is fine).
   d == 0: the original operation is undefined behaviour.  The preheader uses
   ds = d + (d == 0), so the setup never divides by zero (no new UB/trap is
   introduced on a path that did not divide before, e.g. a zero-trip loop),
   and the in-loop result for d == 0 is an unspecified value.

   Profitability (hardware model, plugin arguments):
     benefit = sum over rewritten stmts of freq(stmt) * (occ(kind) - seq(stmt))
     cost    = freq(preheader edge) * setup(kind)
   freq() is the static/feedback profile relative to the function entry;
   expected executions per setup E = sum freq(stmt) / freq(preheader).  If the
   profile is unusable, E is derived from estimated_loop_iterations_int along
   the loop nest.  The loop's max/likely-max niter bound must allow at least
   min-trips iterations.  Rewrite iff benefit > cost and E >= min-trips.

   Plugin args:
     div32-occupancy=N  divider occupancy for 32-bit ops (default 34)
     div64-occupancy=N  divider occupancy for 64-bit ops (default 66)
     mul-latency=N      pipelined mul/mulhu latency (default 3)
     u64-setup-extra=N  extra cycles of the 128/64 libcall setup (default 176;
                        the whole u64 setup measures ~190 cycles on MegaBoomV3)
     w64-guessed=1      let a guessed (non-FDO) profile supply E for 64-bit
                        kinds (default 0: 64-bit kinds need FDO or a niter
                        estimate, since the guessed E of an unknown-trip loop
                        overstates reality, e.g. mcf spec_qsort 4.80 vs 2.03)
     min-trips=N        minimum expected executions per setup (default 2)
     kinds=u32,s32,u64,s64   which kinds to handle (default all)
     force=1            ignore profitability (testing only)
     u32-quot=inc|mask  u32/s32 quotient method (default inc)
     verbose=1          decisions on stderr
   Dump: -fdump-tree-boom_invariant_div (decisions + final GIMPLE).  */

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
#include "tree-ssa-loop-niter.h"
#include "tree-scalar-evolution.h"
#include "tree-eh.h"
#include "fold-const.h"
#include "stringpool.h"
#include "value-range.h"
#include "value-query.h"
#include "sreal.h"
#include "tree-cfg.h"
#include "predict.h"

#include <vector>
#include <map>
#include <string>

int plugin_is_GPL_compatible;

static unsigned div32_occ = 34;
static unsigned div64_occ = 66;
static unsigned mul_lat = 3;
static unsigned u64_setup_extra = 176;  /* setup ~190 cycles on MegaBoomV3 RTL */
static bool w64_guessed = false;  /* trust a guessed profile for 64-bit kinds */
static double min_trips = 2;
static bool force = false;
static bool u32_inc = true;  /* u32 quotient: increment method (default) or d==1 mask */
static int verbose = 0;
static bool en_u32 = true, en_s32 = true, en_u64 = true, en_s64 = true;

static unsigned long long n_seen, n_rewritten, n_groups, n_groups_rewritten;

enum kind_t { K_U32, K_S32, K_U64, K_S64 };
static const char *kind_name[] = {"u32", "s32", "u64", "s64"};

struct cand {
  gimple *stmt;
  enum tree_code code;
  bool n_nonneg;    /* signed kinds: dividend known >= 0 */
  sreal freq;
  int seq;
};

struct group {
  class loop *loop;
  tree d;
  kind_t kind;
  bool d_pos;       /* signed: divisor known > 0 */
  bool d_not1;      /* |d| known != 1 */
  bool has_div = false, has_mod = false;
  std::vector<cand> stmts;
};

/* ------------------------------------------------------------------ */
/* Range helpers (global SSA range info left by VRP/ranger).           */

static bool range_of(tree t, int_range_max &r) {
  if (TREE_CODE(t) == INTEGER_CST) {
    r = int_range_max(TREE_TYPE(t), wi::to_wide(t), wi::to_wide(t));
    return true;
  }
  if (TREE_CODE(t) != SSA_NAME || !INTEGRAL_TYPE_P(TREE_TYPE(t)))
    return false;
  if (!get_global_range_query()->range_of_expr(r, t) || r.undefined_p() ||
      r.varying_p())
    return false;
  return true;
}

static bool known_nonneg(tree t) {
  int_range_max r;
  if (!range_of(t, r))
    return false;
  return !wi::neg_p(r.lower_bound(), SIGNED);
}

/* Signed: d > 0.  */
static bool known_pos(tree t) {
  int_range_max r;
  if (!range_of(t, r))
    return false;
  return wi::gts_p(r.lower_bound(), 0);
}

/* |d| != 1 (and d != 0 is not needed: d == 0 is UB).  */
static bool known_not_unit(tree t, bool is_unsigned) {
  int_range_max r;
  if (!range_of(t, r))
    return false;
  unsigned prec = TYPE_PRECISION(TREE_TYPE(t));
  int_range_max one(TREE_TYPE(t), wi::one(prec), wi::one(prec));
  int_range_max tmp = r;
  tmp.intersect(one);
  if (!tmp.undefined_p())
    return false;
  if (!is_unsigned) {
    int_range_max m1(TREE_TYPE(t), wi::minus_one(prec), wi::minus_one(prec));
    tmp = r;
    tmp.intersect(m1);
    if (!tmp.undefined_p())
      return false;
  }
  return true;
}

/* ------------------------------------------------------------------ */
/* GIMPLE emission helpers.                                            */

static tree u64t, s64t, u128t, uintt;

static tree emit(gimple_seq *seq, enum tree_code code, tree type, tree a,
                 tree b = NULL_TREE) {
  tree r = make_ssa_name(type);
  gimple *g = b ? gimple_build_assign(r, code, a, b)
                : gimple_build_assign(r, code, a);
  gimple_seq_add_stmt(seq, g);
  return r;
}

static tree conv(gimple_seq *seq, tree type, tree x) {
  if (types_compatible_p(type, TREE_TYPE(x)))
    return x;
  if (TREE_CODE(x) == INTEGER_CST)
    return fold_convert(type, x);
  return emit(seq, NOP_EXPR, type, x);
}

static tree cst64(unsigned long long v) {
  return build_int_cst_type(u64t, (HOST_WIDE_INT)v);
}

/* bool (a CODE b) zero-extended to u64.  */
static tree cmp64(gimple_seq *seq, enum tree_code code, tree a, tree b) {
  tree c = emit(seq, code, boolean_type_node, a, b);
  return emit(seq, NOP_EXPR, u64t, c);
}

/* Arithmetic sign mask of a value already converted to the signed 64-bit
   type: 0 or all ones, as u64.  */
static tree signmask64(gimple_seq *seq, tree s) {
  tree sh = emit(seq, RSHIFT_EXPR, s64t, s, build_int_cst(uintt, 63));
  return conv(seq, u64t, sh);
}

/* |x| for x already in u64 with sign mask sm.  */
static tree absval(gimple_seq *seq, tree xu, tree sm) {
  tree x1 = emit(seq, BIT_XOR_EXPR, u64t, xu, sm);
  return emit(seq, MINUS_EXPR, u64t, x1, sm);
}

/* Per-group setup values (preheader SSA names).  */
struct setup_vals {
  tree ds;     /* divisor magnitude, 0 replaced by 1, u64 */
  tree c;      /* U32: Lemire c = ceil(2^64/d) (mod, mask-quotient);  U64: GM m' */
  tree cd;     /* U32: c' = floor((2^64-1)/d) for the increment quotient */
  tree m1;     /* U32: -(ds == 1) mask, or NULL if d known != 1 */
  tree sh1, sh2;  /* U64 shifts (unsigned int) */
  tree sd;     /* signed: sign mask of d (u64), or NULL if d known > 0 */
};

static setup_vals build_setup(gimple_seq *seq, const group &g) {
  setup_vals v = {};
  tree d = g.d;
  tree du;
  if (g.kind == K_S32 || g.kind == K_S64) {
    tree ds64 = conv(seq, s64t, d);
    du = conv(seq, u64t, ds64);
    if (!g.d_pos) {
      v.sd = signmask64(seq, ds64);
      du = absval(seq, du, v.sd);
    }
  } else {
    du = conv(seq, u64t, d);
  }
  /* ds = du + (du == 0): never divide by zero in the preheader.  */
  tree z = cmp64(seq, EQ_EXPR, du, cst64(0));
  v.ds = emit(seq, PLUS_EXPR, u64t, du, z);

  if (g.kind == K_U32 || g.kind == K_S32) {
    tree c0 = emit(seq, TRUNC_DIV_EXPR, u64t, cst64(~0ULL), v.ds);
    v.cd = c0;
    if (g.has_mod || !u32_inc)
      v.c = emit(seq, PLUS_EXPR, u64t, c0, cst64(1));
    if (!u32_inc && g.has_div && !g.d_not1) {
      tree one = cmp64(seq, EQ_EXPR, v.ds, cst64(1));
      v.m1 = emit(seq, NEGATE_EXPR, u64t, one);
    }
  } else {
    /* x = ds - 1; xs = x | (x == 0); lm1 = 63 - clz(xs)
       (lm1 = l - 1 for ds >= 2, 0 for ds == 1).  */
    tree x = emit(seq, MINUS_EXPR, u64t, v.ds, cst64(1));
    tree xz = cmp64(seq, EQ_EXPR, x, cst64(0));
    tree xs = emit(seq, BIT_IOR_EXPR, u64t, x, xz);
    tree xsl = conv(seq, long_long_unsigned_type_node, xs);
    tree clz = make_ssa_name(integer_type_node);
    gcall *call = gimple_build_call(builtin_decl_implicit(BUILT_IN_CLZLL), 1, xsl);
    gimple_call_set_lhs(call, clz);
    gimple_seq_add_stmt(seq, call);
    tree clzu = conv(seq, uintt, clz);
    tree lm1 = emit(seq, MINUS_EXPR, uintt, build_int_cst(uintt, 63), clzu);
    /* h = 2^l - ds, computed as ((1 << lm1) << 1) - ds (wraps for l = 64).
       For ds == 1 this gives h = 1 and m' = (2^64 / 1) + 1 mod 2^64 = 1,
       which is the correct l = 0 multiplier; the shifts below are then 0. */
    tree p = emit(seq, LSHIFT_EXPR, u64t, cst64(1), lm1);
    tree p2 = emit(seq, LSHIFT_EXPR, u64t, p, build_int_cst(uintt, 1));
    tree h = emit(seq, MINUS_EXPR, u64t, p2, v.ds);
    tree h128 = conv(seq, u128t, h);
    tree num = emit(seq, LSHIFT_EXPR, u128t, h128, build_int_cst(uintt, 64));
    tree d128 = conv(seq, u128t, v.ds);
    tree q128 = emit(seq, TRUNC_DIV_EXPR, u128t, num, d128);
    tree m0 = conv(seq, u64t, q128);
    v.c = emit(seq, PLUS_EXPR, u64t, m0, cst64(1));
    tree ne1 = emit(seq, NE_EXPR, boolean_type_node, v.ds, cst64(1));
    v.sh1 = conv(seq, uintt, ne1);
    v.sh2 = lm1;
  }
  return v;
}

/* Unsigned core: n (u64, < 2^32 for 32-bit kinds) -> quotient or remainder
   magnitude (u64).  */
static tree core_u32(gimple_seq *seq, const setup_vals &v, tree n, bool div) {
  if (div && u32_inc) {
    /* q = mulhu(c', n + 1), c' = floor((2^64-1)/d): exact for all
       1 <= d < 2^32, 0 <= n < 2^32 (n + 1 cannot wrap in 64 bits).  */
    tree n1 = emit(seq, PLUS_EXPR, u64t, n, cst64(1));
    return emit(seq, MULT_HIGHPART_EXPR, u64t, v.cd, n1);
  }
  if (div) {
    tree t = emit(seq, MULT_HIGHPART_EXPR, u64t, v.c, n);
    if (v.m1) {
      tree a = emit(seq, BIT_AND_EXPR, u64t, n, v.m1);
      t = emit(seq, PLUS_EXPR, u64t, t, a);
    }
    return t;
  }
  tree lo = emit(seq, MULT_EXPR, u64t, v.c, n);
  return emit(seq, MULT_HIGHPART_EXPR, u64t, lo, v.ds);
}

static tree core_u64(gimple_seq *seq, const setup_vals &v, tree n, bool div) {
  tree t = emit(seq, MULT_HIGHPART_EXPR, u64t, v.c, n);
  tree dl = emit(seq, MINUS_EXPR, u64t, n, t);
  tree d1 = emit(seq, RSHIFT_EXPR, u64t, dl, v.sh1);
  tree s = emit(seq, PLUS_EXPR, u64t, t, d1);
  tree q = emit(seq, RSHIFT_EXPR, u64t, s, v.sh2);
  if (div)
    return q;
  tree qd = emit(seq, MULT_EXPR, u64t, q, v.ds);
  return emit(seq, MINUS_EXPR, u64t, n, qd);
}

static void rewrite(const group &g, const setup_vals &v, const cand &c) {
  gimple *stmt = c.stmt;
  gimple_stmt_iterator gsi = gsi_for_stmt(stmt);
  tree lhs = gimple_assign_lhs(stmt);
  tree type = TREE_TYPE(lhs);
  tree n = gimple_assign_rhs1(stmt);
  bool div = c.code == TRUNC_DIV_EXPR;
  gimple_seq seq = NULL;
  tree res;
  bool sgn = g.kind == K_S32 || g.kind == K_S64;
  bool w32 = g.kind == K_U32 || g.kind == K_S32;
  if (!sgn) {
    tree nu = conv(&seq, u64t, n);
    res = w32 ? core_u32(&seq, v, nu, div) : core_u64(&seq, v, nu, div);
  } else {
    tree ns = conv(&seq, s64t, n);
    tree nu = conv(&seq, u64t, ns);
    tree sn = NULL_TREE;
    if (!c.n_nonneg) {
      sn = signmask64(&seq, ns);
      nu = absval(&seq, nu, sn);
    }
    tree mag = w32 ? core_u32(&seq, v, nu, div) : core_u64(&seq, v, nu, div);
    /* quotient sign = sign(n) ^ sign(d); remainder sign = sign(n).  */
    tree s;
    if (div)
      s = sn && v.sd ? emit(&seq, BIT_XOR_EXPR, u64t, sn, v.sd) : (sn ? sn : v.sd);
    else
      s = sn;
    res = s ? absval(&seq, mag, s) : mag;
  }
  gsi_insert_seq_before(&gsi, seq, GSI_SAME_STMT);
  if (types_compatible_p(type, TREE_TYPE(res)))
    gimple_assign_set_rhs_with_ops(&gsi, SSA_NAME, res);
  else
    gimple_assign_set_rhs_with_ops(&gsi, NOP_EXPR, res);
  update_stmt(gsi_stmt(gsi));
}

/* ------------------------------------------------------------------ */
/* Cost model.  Cycle estimates of the in-loop replacement (latency of the
   dependent chain).  */

static int seq_cost(kind_t k, bool div, bool m1, bool n_abs, bool sign_fix) {
  int L = (int)mul_lat;
  int c = 0;
  if (n_abs)
    c += 3;  /* sra, xor, sub */
  switch (k) {
  case K_U32: case K_S32:
    c += 1;  /* zero/sign extension */
    c += div ? L + (u32_inc ? 1 : (m1 ? 2 : 0)) : 2 * L;
    break;
  case K_U64: case K_S64:
    c += L + 4 + (div ? 0 : L + 1);
    break;
  }
  if (sign_fix)
    c += 2;
  return c;
}

static int occ(kind_t k) {
  return (k == K_U32 || k == K_S32) ? (int)div32_occ : (int)div64_occ;
}

static int setup_cost(const group &g) {
  int c = 4;  /* conversions + d==0 guard */
  if (g.kind == K_S32 || g.kind == K_S64)
    c += g.d_pos ? 1 : 4;
  if (g.kind == K_U32 || g.kind == K_S32)
    c += (int)div64_occ + (g.has_mod || !u32_inc ? 1 : 0) +
         (!u32_inc && g.has_div && !g.d_not1 ? 2 : 0);
  else
    c += 10 /* clz libcall-free path + shifts */ + (int)u64_setup_extra;
  return c;
}

/* ------------------------------------------------------------------ */

static bool kind_of(tree type, kind_t *k) {
  if (!INTEGRAL_TYPE_P(type) || TREE_CODE(type) == BOOLEAN_TYPE)
    return false;
  unsigned p = TYPE_PRECISION(type);
  bool u = TYPE_UNSIGNED(type);
  /* Narrower than 32 bits (e.g. unsigned short division after
     shorten_binary_op): operands extend exactly into the 32-bit method. */
  if (p <= 32 && p >= 2) {
    *k = u ? K_U32 : K_S32;
  } else if (p == 64 && TYPE_MODE(type) == DImode) {
    if (!u128t)
      return false;
    *k = u ? K_U64 : K_S64;
  } else
    return false;
  switch (*k) {
  case K_U32: return en_u32;
  case K_S32: return en_s32;
  case K_U64: return en_u64;
  case K_S64: return en_s64;
  }
  return false;
}

static sreal edge_freq(function *fun, edge e, bool *ok) {
  bool known = false;
  sreal f = e->count().to_sreal_scale(ENTRY_BLOCK_PTR_FOR_FN(fun)->count, &known);
  if (!known)
    *ok = false;
  return f;
}

static sreal bb_freq(function *fun, basic_block bb, bool *ok) {
  bool known = false;
  sreal f = bb->count.to_sreal_scale(ENTRY_BLOCK_PTR_FOR_FN(fun)->count, &known);
  if (!known)
    *ok = false;
  return f;
}

/* Expected number of executions of BB per entry of LOOP from niter
   estimates (product along the nest); -1 if unknown.  */
static double niter_execs(basic_block bb, class loop *L) {
  double e = 1;
  for (class loop *l = bb->loop_father; l; l = loop_outer(l)) {
    HOST_WIDE_INT est = estimated_loop_iterations_int(l);
    if (est < 0)
      return -1;
    e *= (double)(est + 1);
    if (l == L)
      break;
  }
  return e;
}

static void note(FILE *f, const char *fmt, ...) ATTRIBUTE_PRINTF_2;
static void note(FILE *f, const char *fmt, ...) {
  va_list ap;
  if (f) {
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
  }
  if (verbose) {
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
  }
}

static unsigned int run(function *fun) {
  /* Global type nodes do not exist yet at plugin_init time.  */
  u64t = long_long_unsigned_type_node;
  s64t = long_long_integer_type_node;
  uintt = unsigned_type_node;
  u128t = unsigned_intTI_type_node;
  /* loop_optimizer_init(LOOPS_NORMAL) creates preheader blocks.  Skip
     functions with no division by an SSA name so they are left untouched,
     and clean the CFG afterwards when nothing was rewritten.  */
  {
    bool any = false;
    basic_block b;
    FOR_EACH_BB_FN(b, fun) {
      for (gimple_stmt_iterator gsi = gsi_start_bb(b); !any && !gsi_end_p(gsi);
           gsi_next(&gsi)) {
        gimple *st = gsi_stmt(gsi);
        if (is_gimple_assign(st) &&
            (gimple_assign_rhs_code(st) == TRUNC_DIV_EXPR ||
             gimple_assign_rhs_code(st) == TRUNC_MOD_EXPR) &&
            TREE_CODE(gimple_assign_rhs2(st)) == SSA_NAME)
          any = true;
      }
      if (any)
        break;
    }
    if (!any)
      return 0;
  }
  unsigned long long rewritten_before = n_groups_rewritten;
  loop_optimizer_init(LOOPS_NORMAL);
  scev_initialize();
  const char *fname = function_name(fun);

  std::vector<group> groups;
  std::map<std::pair<int, unsigned>, size_t> index;

  basic_block bb;
  FOR_EACH_BB_FN(bb, fun) {
    if (bb->loop_father == NULL || loop_outer(bb->loop_father) == NULL)
      continue;  /* not in a loop */
    for (gimple_stmt_iterator gsi = gsi_start_bb(bb); !gsi_end_p(gsi);
         gsi_next(&gsi)) {
      gimple *stmt = gsi_stmt(gsi);
      if (!is_gimple_assign(stmt))
        continue;
      enum tree_code code = gimple_assign_rhs_code(stmt);
      if (code != TRUNC_DIV_EXPR && code != TRUNC_MOD_EXPR)
        continue;
      tree d = gimple_assign_rhs2(stmt);
      tree type = TREE_TYPE(gimple_assign_lhs(stmt));
      kind_t k;
      if (TREE_CODE(d) != SSA_NAME || !kind_of(type, &k))
        continue;
      if (stmt_could_throw_p(fun, stmt))
        continue;
      tree n0 = gimple_assign_rhs1(stmt);
      if (SSA_NAME_OCCURS_IN_ABNORMAL_PHI(d) ||
          (TREE_CODE(n0) == SSA_NAME && SSA_NAME_OCCURS_IN_ABNORMAL_PHI(n0)))
        continue;
      n_seen++;
      basic_block dbb = SSA_NAME_IS_DEFAULT_DEF(d) ? NULL
                        : gimple_bb(SSA_NAME_DEF_STMT(d));
      /* Candidate loops: innermost .. outermost loop in which d is
         invariant.  Pick the one whose preheader runs least often,
         preferring the outermost on ties.  */
      class loop *best = NULL;
      sreal best_f = 0;
      for (class loop *l = bb->loop_father; loop_outer(l); l = loop_outer(l)) {
        if (dbb && flow_bb_inside_loop_p(l, dbb))
          break;
        bool ok = true;
        sreal f = edge_freq(fun, loop_preheader_edge(l), &ok);
        if (!best || (ok && f <= best_f)) {
          best = l;
          best_f = f;
        }
      }
      if (!best) {
        note(dump_file, "[%s] skip: divisor not invariant in innermost loop %d\n",
             fname, bb->loop_father->num);
        continue;
      }
      std::pair<int, unsigned> key(best->num, SSA_NAME_VERSION(d));
      size_t gi;
      auto it = index.find(key);
      if (it == index.end()) {
        group g;
        g.loop = best;
        g.d = d;
        g.kind = k;
        bool u = k == K_U32 || k == K_U64;
        g.d_pos = !u && known_pos(d);
        g.d_not1 = known_not_unit(d, u);
        gi = groups.size();
        groups.push_back(g);
        index[key] = gi;
      } else
        gi = it->second;
      group &g = groups[gi];
      cand c;
      c.stmt = stmt;
      c.code = code;
      bool u = k == K_U32 || k == K_U64;
      c.n_nonneg = !u && known_nonneg(gimple_assign_rhs1(stmt));
      bool ok = true;
      c.freq = bb_freq(fun, bb, &ok);
      bool div = code == TRUNC_DIV_EXPR;
      bool sign_fix = !u && (div ? !(c.n_nonneg && g.d_pos) : !c.n_nonneg);
      c.seq = seq_cost(k, div, !g.d_not1, !u && !c.n_nonneg, sign_fix);
      if (div) g.has_div = true; else g.has_mod = true;
      g.stmts.push_back(c);
    }
  }

  for (group &g : groups) {
    n_groups++;
    bool ok = true;
    edge pe = loop_preheader_edge(g.loop);
    sreal pf = edge_freq(fun, pe, &ok);
    sreal stmt_f = 0, benefit = 0;
    for (const cand &c : g.stmts) {
      bool okb = true;
      bb_freq(fun, gimple_bb(c.stmt), &okb);
      ok &= okb;
      stmt_f += c.freq;
      benefit += c.freq * sreal(occ(g.kind) - c.seq);
    }
    int sc = setup_cost(g);
    double execs;
    const char *src;
    bool prof_ok = ok && pf > 0 && profile_status_for_fn(fun) != PROFILE_ABSENT;
    if (prof_ok) {
      execs = (stmt_f / pf).to_double();
      src = profile_status_for_fn(fun) == PROFILE_READ ? "profile(fdo)"
                                                       : "profile(guessed)";
    }
    bool w64 = g.kind == K_U64 || g.kind == K_S64;
    bool fdo = prof_ok && profile_status_for_fn(fun) == PROFILE_READ;
    if (!prof_ok || (w64 && !fdo && !w64_guessed)) {
      execs = 0;
      for (const cand &c : g.stmts) {
        double e = niter_execs(gimple_bb(c.stmt), g.loop);
        if (e < 0) { execs = -1; break; }
        execs += e;
      }
      src = "niter-estimate";
    }
    /* Cap by the niter upper bounds: a statement cannot execute more often
       per setup than the product of (max_niter + 1) from its loop up to
       the setup loop.  */
    {
      double cap = 0;
      for (const cand &c : g.stmts) {
        double e = 1;
        for (class loop *l = gimple_bb(c.stmt)->loop_father; l; l = loop_outer(l)) {
          HOST_WIDE_INT b = max_loop_iterations_int(l);
          if (b < 0 || b > (HOST_WIDE_INT)1 << 40) { e = -1; break; }
          e *= (double)(b + 1);
          if (l == g.loop)
            break;
        }
        if (e < 0) { cap = -1; break; }
        cap += e;
      }
      if (cap >= 0 && execs > cap)
        execs = cap;
    }
    HOST_WIDE_INT est = estimated_loop_iterations_int(g.loop);
    HOST_WIDE_INT mx = max_loop_iterations_int(g.loop);
    HOST_WIDE_INT lmx = likely_max_loop_iterations_int(g.loop);
    double per_exec_gain = 0;
    for (const cand &c : g.stmts)
      per_exec_gain += occ(g.kind) - c.seq;
    per_exec_gain /= g.stmts.size();
    double gain = execs * per_exec_gain;

    bool go;
    const char *why;
    if (force) {
      go = true; why = "force";
    } else if (optimize_loop_for_size_p(g.loop)) {
      go = false; why = "loop optimized for size";
    } else if (execs < 0) {
      go = false;
      why = w64 && prof_ok ? "64-bit kind needs FDO or a niter estimate"
                           : "no profile and no niter estimate";
    } else if (mx >= 0 && (double)(mx + 1) * g.stmts.size() < min_trips) {
      go = false; why = "max niter bound below min-trips";
    } else if (lmx >= 0 && (double)(lmx + 1) * g.stmts.size() < min_trips) {
      go = false; why = "likely-max niter bound below min-trips";
    } else if (execs < min_trips) {
      go = false; why = "expected executions below min-trips";
    } else if (!(gain > (double)sc)) {
      go = false; why = "setup cost not amortized";
    } else {
      go = true; why = "profitable";
    }

    note(dump_file,
         "[%s] loop %d (depth %d) divisor ", fname, g.loop->num,
         loop_depth(g.loop));
    if (dump_file)
      print_generic_expr(dump_file, g.d, TDF_SLIM);
    if (verbose)
      print_generic_expr(stderr, g.d, TDF_SLIM);
    note(dump_file,
         " kind=%s ops=%zu (shared setup) d_pos=%d d_not1=%d | "
         "E=%.2f [%s] est_niter=%lld max_niter=%lld likely_max=%lld | "
         "occ=%d avg_seq=%.1f gain=%.1f setup=%d -> %s (%s)\n",
         kind_name[g.kind], g.stmts.size(), g.d_pos, g.d_not1, execs, src,
         (long long)est, (long long)mx, (long long)lmx, occ(g.kind),
         occ(g.kind) - per_exec_gain, gain, sc, go ? "REWRITE" : "keep", why);
    if (!go)
      continue;

    gimple_seq seq = NULL;
    setup_vals v = build_setup(&seq, g);
    gsi_insert_seq_on_edge_immediate(pe, seq);
    for (const cand &c : g.stmts) {
      if (dump_file) {
        fprintf(dump_file, "  rewrite: ");
        print_gimple_stmt(dump_file, c.stmt, 0, TDF_SLIM);
      }
      rewrite(g, v, c);
      n_rewritten++;
    }
    n_groups_rewritten++;
  }

  scev_finalize();
  loop_optimizer_finalize();
  free_dominance_info(CDI_DOMINATORS);
  return n_groups_rewritten == rewritten_before ? TODO_cleanup_cfg : 0;
}

namespace {
const pass_data pass_data_inv = {
    GIMPLE_PASS, "boom_invariant_div", OPTGROUP_LOOP, TV_NONE,
    PROP_cfg | PROP_ssa, 0, 0, 0, TODO_update_ssa_only_virtuals};

class pass_inv : public gimple_opt_pass {
 public:
  pass_inv(gcc::context *ctxt) : gimple_opt_pass(pass_data_inv, ctxt) {}
  bool gate(function *fun) override {
    return optimize > 0 && number_of_loops(fun) > 1;
  }
  unsigned int execute(function *fun) override { return run(fun); }
};
}  // namespace

static void finish(void *, void *) {
  if (verbose)
    fprintf(stderr,
            "boom_invariant_div: seen=%llu rewritten=%llu groups=%llu "
            "groups_rewritten=%llu\n",
            n_seen, n_rewritten, n_groups, n_groups_rewritten);
}

int plugin_init(struct plugin_name_args *info, struct plugin_gcc_version *version) {
  if (!plugin_default_version_check(version, &gcc_version))
    return 1;
  for (int i = 0; i < info->argc; i++) {
    const char *k = info->argv[i].key;
    const char *v = info->argv[i].value ? info->argv[i].value : "1";
    if (!strcmp(k, "div32-occupancy")) div32_occ = atoi(v);
    else if (!strcmp(k, "div64-occupancy")) div64_occ = atoi(v);
    else if (!strcmp(k, "mul-latency")) mul_lat = atoi(v);
    else if (!strcmp(k, "u64-setup-extra")) u64_setup_extra = atoi(v);
    else if (!strcmp(k, "min-trips")) min_trips = atof(v);
    else if (!strcmp(k, "w64-guessed")) w64_guessed = atoi(v) != 0;
    else if (!strcmp(k, "force")) force = atoi(v) != 0;
    else if (!strcmp(k, "verbose")) verbose = atoi(v);
    else if (!strcmp(k, "u32-quot")) u32_inc = strcmp(v, "mask") != 0;
    else if (!strcmp(k, "kinds")) {
      std::string s(v);
      en_u32 = s.find("u32") != std::string::npos;
      en_s32 = s.find("s32") != std::string::npos;
      en_u64 = s.find("u64") != std::string::npos;
      en_s64 = s.find("s64") != std::string::npos;
    } else
      warning(0, "boom_invariant_div: unknown argument %qs", k);
  }
  /* Heap-allocated: with -fchecking, toplev::finalize deletes the pass
     tree (passes.cc delete_pass_tree), so a static object would be freed. */
  static register_pass_info rp;
  rp.pass = new pass_inv(g);
  rp.reference_pass_name = "optimized";
  rp.ref_pass_instance_number = 1;
  rp.pos_op = PASS_POS_INSERT_AFTER;
  register_callback(info->base_name, PLUGIN_PASS_MANAGER_SETUP, nullptr, &rp);
  register_callback(info->base_name, PLUGIN_FINISH, finish, nullptr);
  return 0;
}
