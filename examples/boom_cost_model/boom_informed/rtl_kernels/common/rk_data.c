/* Deterministic inputs.  Compiled once with stock flags; identical on host. */
#include "rk.h"
u64 qs_src[QS_N];
volatile u64 qs_es;
u32 tt_size;
#ifdef RK_NEED_TT
static u64 tt64_store[TT_ENT];
#endif
#ifdef RK_NEED_TT
static tte_t tt32_store[TT_ENT];
static tte_t tt32_pristine[TT_ENT];
const tte_t *tt32_orig = tt32_pristine;
#else
const tte_t *tt32_orig;
#endif
u64 *tt64;
tte_t *tt32;
u32 chain[CH_N];
kid_t uct_init[UCT_KIDS];
float kd_pts[KD_N * KD_DIM_MAX];
float kd_q[KD_Q * KD_DIM_MAX];
volatile s32 kd_dim;
unsigned char mc_bytes[MC_N];
s64 mc_big[MC_N];
u64 tc_small[TC_R * TC_MAXT];
u64 tc_big[TC_R * TC_MAXT];
u64 tc_div_big[TC_R];
u32 tc_div32[TC_R];

static u64 rs = 0x9E3779B97F4A7C15ULL;
static u64 rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }

/* kd tree in heap layout: node i's point lies in its box; children split the
   box at node's coordinate along axis depth % dim (built top-down, O(N)). */
static void kd_build(int node, int depth, int dim, float *lo, float *hi) {
  if (node >= KD_N) return;
  for (int k = 0; k < dim; k++) {
    float u = (float)(rnd() & 0xffff) / 65536.0f;
    kd_pts[node * dim + k] = lo[k] + (hi[k] - lo[k]) * (0.25f + 0.5f * u);
  }
  int ax = depth % dim;
  float split = kd_pts[node * dim + ax];
  float l2[KD_DIM_MAX], h2[KD_DIM_MAX];
  for (int k = 0; k < dim; k++) { l2[k] = lo[k]; h2[k] = hi[k]; }
  h2[ax] = split;
  kd_build(2 * node + 1, depth + 1, dim, l2, h2);
  h2[ax] = hi[ax]; l2[ax] = split;
  kd_build(2 * node + 2, depth + 1, dim, l2, h2);
}

void rk_data_init(void) {
  for (int i = 0; i < QS_N; i++) qs_src[i] = rnd() % 5000; /* duplicates on purpose */
  qs_es = 8;
  tt_size = 12289u;
#ifdef RK_NEED_TT
  tt64 = tt64_store;
  tt32 = tt32_store;
  for (u32 i = 0; i < TT_ENT; i++) {
    u64 r = rnd();
    tt64[i] = (i % 3 == 0) ? 0 : r;
    tt32[i].tag = (u32)(r >> 40);
    tt32[i].data = (u32)r;
    tt32_pristine[i] = tt32[i];
  }
#endif
  for (int i = 0; i < CH_N; i++) chain[i] = (u32)(rnd() % CH_N);
  for (int i = 0; i < UCT_KIDS; i++) {
    uct_init[i].visits = (i % 5 == 0) ? 0 : (s32)(rnd() % 60 + 1);
    uct_init[i].wins = (s32)(rnd() % (u64)(uct_init[i].visits + 1));
    uct_init[i].prior = (float)(rnd() & 0xfff) / 4096.0f;
    uct_init[i].pad = 0;
  }
  kd_dim = 3;
  {
    float lo[KD_DIM_MAX] = {0, 0, 0, 0}, hi[KD_DIM_MAX] = {100, 100, 100, 100};
    kd_build(0, 0, 3, lo, hi);
  }
  for (int i = 0; i < KD_Q * 3; i++) kd_q[i] = (float)(rnd() % 10000) / 100.0f;
  for (int i = 0; i < MC_N; i++) { mc_bytes[i] = (unsigned char)rnd(); mc_big[i] = (s64)(rnd() >> 2); }
  for (int i = 0; i < TC_R * TC_MAXT; i++) { tc_small[i] = (rnd() % 400) * 8 + 8 * (rnd() % 2); tc_big[i] = rnd() >> 1; }
  for (int i = 0; i < TC_R; i++) { tc_div_big[i] = (rnd() >> 44) | 0x80000; tc_div32[i] = (u32)(rnd() % 2000 + 3); }
}
