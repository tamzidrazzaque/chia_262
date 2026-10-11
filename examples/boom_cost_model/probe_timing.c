#include <stdint.h>
#include <stdio.h>

#define DECLARE(T) \
  uint32_t probe_mul_##T(const uint32_t *, uint32_t *, int, int); \
  uint32_t probe_shift_##T(const uint32_t *, uint32_t *, int, int); \
  uint32_t probe_add_##T(const uint32_t *, uint32_t *, int, int); \
  uint32_t probe_load_##T(const uint32_t *, uint32_t *, int, int)
DECLARE(rocket);
DECLARE(generic_ooo);
DECLARE(xiangshan_nanhu);

static uint64_t nodes[64] __attribute__((aligned(64)));
static uint32_t out[8], expected[8];
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

static uint32_t reference(int kernel, int n, int width) {
  uint32_t sum = 0;
  for (int j = 0; j < width; ++j) {
    uint32_t value = 0x1234u + (uint32_t)j;
    if (kernel < 2) {
      /* Exponentiation by squaring is independent of the probe's sequence. */
      uint32_t factor = 13;
      for (int exponent = n / width; exponent; exponent >>= 1) {
        if (exponent & 1) value *= factor;
        factor *= factor;
      }
    } else if (kernel == 2) value += (uint32_t)(13 * (n / width));
    else value = (uint32_t)(uintptr_t)&nodes[(j + n / width) % 64];
    expected[j] = value;
    sum += value;
  }
  return sum;
}

static int check_output(int width) {
  for (int j = 0; j < width; ++j) if (out[j] != expected[j]) return 0;
  return 1;
}

int main(void) {
  uint32_t (*functions[4][3])(const uint32_t *, uint32_t *, int, int) = {
    {probe_mul_rocket, probe_mul_generic_ooo, probe_mul_xiangshan_nanhu},
    {probe_shift_rocket, probe_shift_generic_ooo, probe_shift_xiangshan_nanhu},
    {probe_add_rocket, probe_add_generic_ooo, probe_add_xiangshan_nanhu},
    {probe_load_rocket, probe_load_generic_ooo, probe_load_xiangshan_nanhu}
  };
  for (int j = 0; j < 64; ++j) nodes[j] = (uint64_t)(uintptr_t)&nodes[(j + 1) % 64];
  const int sizes[] = {128, 512};
  const int widths[] = {1, 8};
  static uint64_t measurements[4][2][2][3][3];
  for (int k = 0; k < 4; ++k)
    for (int size = 0; size < 2; ++size)
      for (int w = 0; w < 2; ++w) {
        uint32_t checksum = reference(k, sizes[size], widths[w]);
        for (int sample = 0; sample < 3; ++sample)
          for (int order = 0; order < 3; ++order) {
            int tune = (sample + order) % 3;
            uint32_t warm = functions[k][tune]((const uint32_t *)nodes, out, sizes[size], widths[w]);
            sink = warm;
            if (warm != checksum || !check_output(widths[w])) return k + 1;
            uint32_t total = 0;
            uint64_t start = cycles();
            for (int repeat = 0; repeat < 2; ++repeat)
              total += functions[k][tune]((const uint32_t *)nodes, out, sizes[size], widths[w]);
            measurements[k][size][w][tune][sample] = cycles() - start;
            sink = total;
            if (total != checksum * 2u || !check_output(widths[w])) return k + 1;
          }
      }
  static char buffer[8192];
  setvbuf(stdout, buffer, _IOFBF, sizeof(buffer));
  for (int k = 0; k < 4; ++k)
    for (int size = 0; size < 2; ++size)
      for (int w = 0; w < 2; ++w)
        for (int tune = 0; tune < 3; ++tune) {
          printf("P %d %d %d %d", k, sizes[size], widths[w], tune);
          for (int s = 0; s < 3; ++s) printf(" %lu", (unsigned long)measurements[k][size][w][tune][s]);
          printf("\n");
        }
  printf("PROBES_OK cases=16 repeats=2 samples=3 block=32\n");
  return 0;
}
