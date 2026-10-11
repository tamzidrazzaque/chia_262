#include <stdint.h>

uint32_t reduction(const uint32_t *a, int n, int streams) {
  (void)streams;
  uint32_t sum = 0;
  for (int i = 0; i < n; ++i) sum += a[i];
  return sum;
}
