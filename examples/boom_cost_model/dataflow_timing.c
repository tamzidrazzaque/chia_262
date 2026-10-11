/* Separate from the historical branch/float experiment. Warm-cache rv64gc,
 * three samples, two calls per sample, no output during measurements. */
#include <stdint.h>
#include <stdio.h>

#define DECLARE(T) \
  uint32_t recurrence_##T(const uint32_t *, int, int); \
  uint32_t independent_streams_##T(const uint32_t *, int, int); \
  uint32_t reduction_##T(const uint32_t *, int, int)
DECLARE(rocket);
DECLARE(generic_ooo);
DECLARE(xiangshan_nanhu);

static uint32_t input[512] __attribute__((aligned(64)));
static volatile uint32_t sink;

static uint64_t cycles(void) {
#ifdef HOST_CHECK
  return 0;
#else
  uint64_t value;
  __asm__ volatile("fence iorw,iorw\n\tcsrr %0,mcycle\n\tfence iorw,iorw"
                   : "=r"(value) : : "memory");
  return value;
#endif
}

/* Scalar reference uses modulo indexing, independently of the specialized
 * kernel loops. Also verifies every warm-up result before timing. */
static uint32_t reference(int kernel, int n, int width) {
  uint32_t states[8], sum = 0;
  for (int j = 0; j < width; ++j) states[j] = 0x1234u + (uint32_t)j;
  for (int i = 0; i < n; ++i) {
    if (kernel == 2) sum += input[i];
    else {
      int j = i % width;
      states[j] = (states[j] ^ input[i]) * 13u + 7u;
    }
  }
  if (kernel != 2)
    for (int j = 0; j < width; ++j) sum += states[j];
  return sum;
}

int main(void) {
  uint32_t (*functions[3][3])(const uint32_t *, int, int) = {
    {recurrence_rocket, recurrence_generic_ooo, recurrence_xiangshan_nanhu},
    {independent_streams_rocket, independent_streams_generic_ooo, independent_streams_xiangshan_nanhu},
    {reduction_rocket, reduction_generic_ooo, reduction_xiangshan_nanhu}
  };
  const int sizes[] = {32, 128, 512};
  const int widths[] = {1, 2, 4, 8};
  static uint64_t measurements[3][3][4][3][3];
  uint32_t state = 0x12345678u;
  for (int i = 0; i < 512; ++i) {
    state = state * 1664525u + 1013904223u;
    input[i] = state;
  }
  for (int size = 0; size < 3; ++size)
    for (int kernel = 0; kernel < 3; ++kernel)
      for (int w = 0; w < (kernel == 1 ? 4 : 1); ++w) {
        int n = sizes[size], width = widths[w];
        uint32_t expected = reference(kernel, n, width);
        for (int sample = 0; sample < 3; ++sample)
          for (int order = 0; order < 3; ++order) {
            int tune = (sample + order) % 3;
            uint32_t warm = functions[kernel][tune](input, n, width);
            sink = warm;
            if (warm != expected) return kernel + 1;
            uint32_t total = 0;
            uint64_t start = cycles();
            for (int repeat = 0; repeat < 2; ++repeat)
              total += functions[kernel][tune](input, n, width);
            measurements[size][kernel][w][tune][sample] = cycles() - start;
            sink = total;
            if (total != expected * 2u) return kernel + 1;
          }
      }
  static char buffer[8192];
  setvbuf(stdout, buffer, _IOFBF, sizeof(buffer));
  for (int size = 0; size < 3; ++size)
    for (int kernel = 0; kernel < 3; ++kernel)
      for (int w = 0; w < (kernel == 1 ? 4 : 1); ++w)
        for (int tune = 0; tune < 3; ++tune) {
          printf("D %d %d %d %d", sizes[size], kernel, widths[w], tune);
          for (int sample = 0; sample < 3; ++sample)
            printf(" %lu", (unsigned long)measurements[size][kernel][w][tune][sample]);
          printf("\n");
        }
  printf("DATAFLOW_OK sizes=32,128,512 widths=1,2,4,8 repeats=2 samples=3\n");
  return 0;
}
