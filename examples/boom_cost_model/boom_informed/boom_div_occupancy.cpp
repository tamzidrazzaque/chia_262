/* Pass: rewrite constant division using BOOM divider occupancy.

   expand_divmod decides div vs mulh from the scalar RTX cost int_div
   (COSTS_N_INSNS units). The scheduling automaton's unpipelined divider
   reservation is a different quantity and is consulted only after a div
   instruction already exists. This pass runs before expand and rewrites
   a constant division when that occupancy exceeds the latency of the
   multiply-high sequence. It does not modify int_div.

   Handles 64-bit signed constant division and remainder whose multiplier
   fits the simple mulh/shift/sign sequence, including a negative divisor
   (same magic as |d|, quotient negated). Unsigned division, precision
   other than 64, powers of two, INT64_MIN, and multipliers that need the
   extra addend are left untouched.
*/
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

int plugin_is_GPL_compatible;

static unsigned occupancy = 66;
static unsigned mul_latency = 3;
static int verbose = 0;
static unsigned rewritten = 0;

static int ceil_log2_u64(unsigned long long d) {
  return 64 - __builtin_clzll(d - 1);
}

static bool choose_multiplier(unsigned long long d, int n, int precision,
                              unsigned long long *multiplier, int *post_shift) {
  int lgup = ceil_log2_u64(d);
  if (lgup > n || lgup > precision)
    return false;
  int pow1 = n + lgup;
  int pow2 = n + lgup - precision;
  unsigned __int128 mlow = ((unsigned __int128)1 << pow1) / d;
  unsigned __int128 mhigh =
      (((unsigned __int128)1 << pow1) | ((unsigned __int128)1 << pow2)) / d;
  int post = lgup;
  while (post > 0) {
    unsigned __int128 ml_lo = mlow >> 1;
    unsigned __int128 mh_lo = mhigh >> 1;
    if (ml_lo >= mh_lo)
      break;
    mlow = ml_lo;
    mhigh = mh_lo;
    post--;
  }
  unsigned __int128 mask = ((unsigned __int128)1 << n) - 1;
  if (mhigh > mask)
    return false;
  *multiplier = (unsigned long long)(mhigh & mask);
  *post_shift = post;
  return true;
}

static bool simple_signed_magic(long long divisor, unsigned long long *magic,
                                int *post) {
  /* 0 is undefined.  +/-1 are not reciprocal multiplies.  divisor <= 1
     used to reject every negative divisor and left the negate path dead. */
  if (divisor == 0 || divisor == 1 || divisor == -1)
    return false;
  unsigned long long abs_d =
      divisor < 0 ? (unsigned long long)(-(unsigned long long)divisor)
                  : (unsigned long long)divisor;
  /* Powers of two, including the magnitude of INT64_MIN (2^63).  The
     multiplier proof does not apply, and signed / -2^63 is not a shift. */
  if (abs_d <= 1 || (abs_d & (abs_d - 1)) == 0)
    return false;
  unsigned long long ml;
  int shift;
  if (!choose_multiplier(abs_d, 64, 63, &ml, &shift))
    return false;
  if (ml >= (1ULL << 63))
    return false;
  if (shift >= 64)
    return false;
  *magic = ml;
  *post = shift;
  return true;
}

static void rewrite_stmt(gimple_stmt_iterator *gsi) {
  gimple *stmt = gsi_stmt(*gsi);
  enum tree_code code = gimple_assign_rhs_code(stmt);
  if (code != TRUNC_DIV_EXPR && code != TRUNC_MOD_EXPR)
    return;
  tree lhs = gimple_assign_lhs(stmt);
  tree op0 = gimple_assign_rhs1(stmt);
  tree op1 = gimple_assign_rhs2(stmt);
  if (TREE_CODE(op1) != INTEGER_CST || !INTEGRAL_TYPE_P(TREE_TYPE(lhs)))
    return;
  if (TYPE_PRECISION(TREE_TYPE(lhs)) != 64 || TYPE_UNSIGNED(TREE_TYPE(lhs)))
    return;
  if (!tree_fits_shwi_p(op1))
    return;
  long long divisor = tree_to_shwi(op1);
  unsigned long long magic;
  int post;
  if (!simple_signed_magic(divisor, &magic, &post))
    return;
  int sequence = (int)mul_latency + 2;
  if ((int)occupancy <= sequence)
    return;

  tree type = TREE_TYPE(lhs);
  tree magic_tree = build_int_cst_type(type, (HOST_WIDE_INT)magic);
  tree post_tree = build_int_cst(integer_type_node, post);
  tree sign_tree = build_int_cst(integer_type_node, 63);

  tree t_mul = make_ssa_name(type);
  gsi_insert_before(gsi, gimple_build_assign(t_mul, MULT_HIGHPART_EXPR, op0, magic_tree),
                    GSI_SAME_STMT);
  tree t_sh = make_ssa_name(type);
  gsi_insert_before(gsi, gimple_build_assign(t_sh, RSHIFT_EXPR, t_mul, post_tree),
                    GSI_SAME_STMT);
  tree t_sign = make_ssa_name(type);
  gsi_insert_before(gsi, gimple_build_assign(t_sign, RSHIFT_EXPR, op0, sign_tree),
                    GSI_SAME_STMT);
  tree t_q = make_ssa_name(type);
  tree shifted = t_sh;
  tree sign = t_sign;
  if (divisor < 0) {
    tree t_neg = make_ssa_name(type);
    gsi_insert_before(gsi, gimple_build_assign(t_neg, MINUS_EXPR, t_sign, t_sh),
                      GSI_SAME_STMT);
    shifted = t_neg;
    sign = NULL_TREE;
  }
  if (sign) {
    gsi_insert_before(gsi, gimple_build_assign(t_q, MINUS_EXPR, shifted, sign),
                      GSI_SAME_STMT);
  } else {
    t_q = shifted;
  }

  if (code == TRUNC_DIV_EXPR) {
    gimple_assign_set_rhs_with_ops(gsi, SSA_NAME, t_q);
  } else {
    tree t_prod = make_ssa_name(type);
    gsi_insert_before(gsi, gimple_build_assign(t_prod, MULT_EXPR, t_q, op1),
                      GSI_SAME_STMT);
    gimple_assign_set_rhs_with_ops(gsi, MINUS_EXPR, op0, t_prod);
  }
  update_stmt(gsi_stmt(*gsi));
  rewritten++;
  if (verbose)
    fprintf(stderr, "boom_div_occupancy: rewrote %s by %lld (occupancy %u)\n",
            code == TRUNC_DIV_EXPR ? "div" : "mod", divisor, occupancy);
}

namespace {
const pass_data boom_pass_data = {
    GIMPLE_PASS, "boom_div_occupancy", OPTGROUP_NONE, TV_NONE,
    PROP_cfg | PROP_ssa, 0, 0, 0, 0};

class pass_boom_div_occupancy : public gimple_opt_pass {
 public:
  pass_boom_div_occupancy(gcc::context *ctxt) : gimple_opt_pass(boom_pass_data, ctxt) {}
  bool gate(function *) override { return true; }
  unsigned int execute(function *fun) override {
    basic_block bb;
    FOR_EACH_BB_FN(bb, fun) {
      for (gimple_stmt_iterator gsi = gsi_start_bb(bb); !gsi_end_p(gsi); gsi_next(&gsi)) {
        gimple *stmt = gsi_stmt(gsi);
        if (is_gimple_assign(stmt))
          rewrite_stmt(&gsi);
      }
    }
    return 0;
  }
};
}  // namespace

int plugin_init(struct plugin_name_args *plugin_info, struct plugin_gcc_version *version) {
  if (!plugin_default_version_check(version, &gcc_version))
    return 1;
  for (int i = 0; i < plugin_info->argc; i++) {
    const char *key = plugin_info->argv[i].key;
    const char *val = plugin_info->argv[i].value;
    if (!strcmp(key, "occupancy") && val)
      occupancy = (unsigned)atoi(val);
    else if (!strcmp(key, "mul-latency") && val)
      mul_latency = (unsigned)atoi(val);
    else if (!strcmp(key, "verbose") && val)
      verbose = atoi(val);
  }
  static pass_boom_div_occupancy pass(g);
  static register_pass_info info;
  info.pass = &pass;
  info.reference_pass_name = "optimized";
  info.ref_pass_instance_number = 1;
  info.pos_op = PASS_POS_INSERT_AFTER;
  register_callback(plugin_info->base_name, PLUGIN_PASS_MANAGER_SETUP, nullptr, &info);
  return 0;
}
