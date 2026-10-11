#include <stdint.h>

/* Each node occupies a cache line. The harness supplies one shuffled cycle
 * of n/16 nodes, and 1 or 4 starting points separated around that cycle.
 * Every width performs the same total 1,024 dependent index loads. */
uint32_t pointer_chase(const uint32_t *data, uint32_t *out, int n, int chains) {
  (void)n;
  uint32_t p0 = out[0];
  if (chains == 1) {
    for (int i = 0; i < 1024; ++i) p0 = data[p0];
    out[0] = p0;
    return p0;
  }
  uint32_t p1 = out[1], p2 = out[2], p3 = out[3];
  for (int i = 0; i < 256; ++i) {
    p0 = data[p0];
    p1 = data[p1];
    p2 = data[p2];
    p3 = data[p3];
  }
  out[0] = p0;
  out[1] = p1;
  out[2] = p2;
  out[3] = p3;
  return p0 + p1 + p2 + p3;
}
