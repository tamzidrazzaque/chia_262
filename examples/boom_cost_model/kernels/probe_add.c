#define PROBE_KIND 2
#include "probe_body.h"

uint32_t probe_add(const uint32_t *data, uint32_t *out, int n, int width) {
  return probe_body(data, out, n, width);
}
