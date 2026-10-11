#include <stdint.h>

/* Input layout: n+taps-1 signal words followed by taps coefficient words.
 * Unsigned integer FIR makes reassociation exact modulo 2^32. */
uint32_t fir(const uint32_t *data, uint32_t *out, int n, int taps) {
  const uint32_t *coeff = data + n + taps - 1;
  uint32_t checksum = 0;
  for (int i = 0; i < n; ++i) {
    uint32_t sum = 0;
    for (int j = 0; j < taps; ++j) sum += data[i + j] * coeff[j];
    out[i] = sum;
    checksum += sum;
  }
  return checksum;
}
