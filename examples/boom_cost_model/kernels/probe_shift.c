#define PROBE_KIND 1
#include "probe_body.h"

uint32_t probe_shift(const uint32_t *data, uint32_t *out, int n, int width) {
  return probe_body(data, out, n, width);
}
