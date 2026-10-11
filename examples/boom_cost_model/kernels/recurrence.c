#include <stdint.h>

/* Unsigned arithmetic deliberately wraps: there is no signed overflow. */
uint32_t recurrence(const uint32_t *a, int n, int streams) {
  (void)streams;
  uint32_t state = 0x1234u;
  for (int i = 0; i < n; ++i) state = (state ^ a[i]) * 13u + 7u;
  return state;
}
