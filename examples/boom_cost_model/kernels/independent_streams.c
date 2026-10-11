#include <stdint.h>

/* Each width consumes n elements in total, with one recurrence per stream.
 * Constant bounds let the compiler keep the states in registers. The switch
 * is outside the hot loop; width is a workload parameter, not an unroll flag.
 */
#define RUN(WIDTH) do { \
  uint32_t states[WIDTH]; \
  for (int j = 0; j < WIDTH; ++j) states[j] = 0x1234u + (uint32_t)j; \
  for (int i = 0; i < n; i += WIDTH) \
    for (int j = 0; j < WIDTH; ++j) \
      states[j] = (states[j] ^ a[i + j]) * 13u + 7u; \
  uint32_t sum = 0; \
  for (int j = 0; j < WIDTH; ++j) sum += states[j]; \
  return sum; \
} while (0)

/* The harness passes only widths 1, 2, 4, 8 and n divisible by width. */
uint32_t independent_streams(const uint32_t *a, int n, int streams) {
  switch (streams) {
    case 1: RUN(1);
    case 2: RUN(2);
    case 4: RUN(4);
    case 8: RUN(8);
    default: return 0;
  }
}
