#include <stdint.h>

/* Row-major A followed by row-major B; straightforward i/j/k order.
 * Keep the complete output observable, not just a reducible checksum. */
uint32_t matmul(const uint32_t *data, uint32_t *out, int n, int unused) {
  (void)unused;
  const uint32_t *b = data + n * n;
  uint32_t checksum = 0;
  for (int i = 0; i < n; ++i)
    for (int j = 0; j < n; ++j) {
      uint32_t sum = 0;
      for (int k = 0; k < n; ++k) sum += data[i * n + k] * b[k * n + j];
      out[i * n + j] = sum;
      checksum += sum;
    }
  return checksum;
}
