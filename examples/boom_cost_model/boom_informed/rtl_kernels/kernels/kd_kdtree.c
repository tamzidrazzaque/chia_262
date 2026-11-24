/* (d) kd-tree range search: split axis = depth % dim, dim a runtime value
   that is invariant in the search loop (32-bit signed remainder).  Explicit
   stack, heap-layout tree.  Pattern only. */
#include "rk.h"

static int __attribute__((noipa)) F(range)(const float *pts, int npts, int dim, const float *q, float r2) {
  int stk_node[64], stk_depth[64];
  int sp = 0, cnt = 0;
  stk_node[sp] = 0; stk_depth[sp] = 0; sp++;
  while (sp > 0) {
    sp--;
    int node = stk_node[sp], depth = stk_depth[sp];
    const float *p = pts + node * dim;
    float d2 = 0.0f;
    for (int k = 0; k < dim; k++) { float t = p[k] - q[k]; d2 += t * t; }
    if (d2 < r2) cnt += node + 1;
    int ax = depth % dim;                     /* remw by invariant dim */
    float diff = q[ax] - p[ax];
    int nearc = 2 * node + 1 + (diff > 0.0f);
    int farc = 2 * node + 2 - (diff > 0.0f);
    if (farc < npts && diff * diff < r2) { stk_node[sp] = farc; stk_depth[sp] = depth + 1; sp++; }
    if (nearc < npts) { stk_node[sp] = nearc; stk_depth[sp] = depth + 1; sp++; }
  }
  return cnt;
}

u64 F(kd_kdtree)(u64 *tm) {
  int dim = kd_dim;
  u64 h = 0xcbf29ce484222325ULL;
  TSTART(tm);
  for (int i = 0; i < KD_Q; i++) {
    int c = F(range)(kd_pts, KD_N, dim, kd_q + i * dim, 400.0f);
    h = rk_mix(h, (u64)c);
  }
  TSTOP(tm);
  return h;
}
