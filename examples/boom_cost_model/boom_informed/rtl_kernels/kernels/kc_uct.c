/* (c) UCT-like child selection: per-child integer win rate scaled by 1000 and
   divided by the child's own visit count, a divide by the constant 200, and
   an FP exploration term c*sqrt(logN / visits).  Pattern only. */
#include "rk.h"

static kid_t kids[UCT_KIDS];

static int __attribute__((noipa)) F(select)(const kid_t *c, int n, s32 parent, float logN) {
  int best = 0;
  float bs = -1e30f;
  for (int i = 0; i < n; i++) {
    s32 v = c[i].visits;
    float s;
    if (v == 0) {
      s = 1e6f + c[i].prior;
    } else {
      s32 wr = c[i].wins * 1000 / v;          /* divide by per-child field */
      s32 lcb = wr - (parent + 1) / 200;      /* divide by constant 200 */
      float ex = 1.4f * __builtin_sqrtf(logN / (float)v);
      s = (float)lcb * 0.001f + ex + c[i].prior / (float)(v + 1);
    }
    if (s > bs) { bs = s; best = i; }
  }
  return best;
}

u64 F(kc_uct)(u64 *tm) {
  for (int i = 0; i < UCT_KIDS; i++) kids[i] = uct_init[i];
  s32 parent = 0;
  for (int i = 0; i < UCT_KIDS; i++) parent += kids[i].visits;
  u64 lcg = 12345, h = 0xcbf29ce484222325ULL;
  TSTART(tm);
  for (int r = 0; r < UCT_ROUNDS; r++) {
    /* log(parent) from the bit length; loop-invariant for one select */
    float logN = 0.6931472f * (float)(64 - __builtin_clzll((u64)parent + 1));
    int b = F(select)(kids, UCT_KIDS, parent, logN);
    lcg = lcg * 6364136223846793005ULL + 1442695040888963407ULL;
    kids[b].visits += 1;
    kids[b].wins += (s32)((lcg >> 33) & 1);
    parent += 1;
    h = rk_mix(h, (u64)b);
  }
  TSTOP(tm);
  return h;
}
