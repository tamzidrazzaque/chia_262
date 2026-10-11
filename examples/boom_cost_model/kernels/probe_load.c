#define PROBE_KIND 3
#include "probe_body.h"

uint32_t probe_load(const uint32_t *data, uint32_t *out, int n, int width) {
  return probe_body(data, out, n, width);
}
