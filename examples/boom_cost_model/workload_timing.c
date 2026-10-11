#include <stdint.h>
#include <stdio.h>

#define DECLARE(T) \
  uint32_t fir_##T(const uint32_t *, uint32_t *, int, int); \
  uint32_t matmul_##T(const uint32_t *, uint32_t *, int, int); \
  uint32_t pointer_chase_##T(const uint32_t *, uint32_t *, int, int)
DECLARE(rocket);
DECLARE(generic_ooo);
DECLARE(xiangshan_nanhu);

static uint32_t data[16384] __attribute__((aligned(64)));
static uint32_t out[512] __attribute__((aligned(64)));
static uint32_t expected[512];
static uint32_t permutation[1024];
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

static uint32_t random_word(uint32_t *state) {
  *state = *state * 1664525u + 1013904223u;
  return *state;
}

/* Reference loops deliberately traverse matrix/reduction axes differently.
 * Pointer expected positions follow the permutation, not the tested loads. */
static int prepare(int kernel, int n, int parameter, uint32_t *checksum) {
  uint32_t state = 0x12345678u;
  *checksum = 0;
  if (kernel == 2) {
    int nodes = n / 16;
    for (int i = 0; i < n; ++i) data[i] = 0;
    for (int i = 0; i < nodes; ++i) permutation[i] = (uint32_t)i;
    for (int i = nodes - 1; i > 0; --i) {
      int j = (int)(random_word(&state) % (uint32_t)(i + 1));
      uint32_t temp = permutation[i];
      permutation[i] = permutation[j];
      permutation[j] = temp;
    }
    for (int i = 0; i < nodes; ++i)
      data[permutation[i] * 16] = permutation[(i + 1) % nodes] * 16;
    for (int j = 0; j < parameter; ++j) {
      int start = j * nodes / parameter;
      expected[j] = permutation[(start + 1024 / parameter) % nodes] * 16;
      *checksum += expected[j];
    }
    return parameter;
  }
  int count = kernel == 0 ? n + 2 * parameter - 1 : 2 * n * n;
  for (int i = 0; i < count; ++i) data[i] = random_word(&state);
  int outputs = kernel == 0 ? n : n * n;
  for (int i = 0; i < outputs; ++i) expected[i] = 0;
  if (kernel == 0) {
    for (int j = parameter - 1; j >= 0; --j)
      for (int i = 0; i < n; ++i)
        expected[i] += data[i + j] * data[n + parameter - 1 + j];
  } else {
    for (int k = 0; k < n; ++k)
      for (int j = 0; j < n; ++j)
        for (int i = 0; i < n; ++i)
          expected[i * n + j] += data[i * n + k] * data[n * n + k * n + j];
  }
  for (int i = 0; i < outputs; ++i) *checksum += expected[i];
  return outputs;
}

static void reset_output(int kernel, int n, int parameter, int outputs) {
  if (kernel == 2)
    for (int j = 0; j < parameter; ++j) out[j] = permutation[j * (n / 16) / parameter] * 16;
  else
    for (int i = 0; i < outputs; ++i) out[i] = 0;
}

static int check_output(int outputs) {
  for (int i = 0; i < outputs; ++i) if (out[i] != expected[i]) return 0;
  return 1;
}

int main(void) {
  uint32_t (*functions[3][3])(const uint32_t *, uint32_t *, int, int) = {
    {fir_rocket, fir_generic_ooo, fir_xiangshan_nanhu},
    {matmul_rocket, matmul_generic_ooo, matmul_xiangshan_nanhu},
    {pointer_chase_rocket, pointer_chase_generic_ooo, pointer_chase_xiangshan_nanhu}
  };
  const int cases[15][3] = {
    {0,32,8}, {0,32,32}, {0,128,8}, {0,128,32}, {0,512,8}, {0,512,32},
    {1,4,0}, {1,8,0}, {1,16,0},
    {2,64,1}, {2,64,4}, {2,4096,1}, {2,4096,4}, {2,16384,1}, {2,16384,4}
  };
  static uint64_t measurements[15][3][3];
  for (int c = 0; c < 15; ++c) {
    int kernel = cases[c][0], n = cases[c][1], parameter = cases[c][2];
    uint32_t checksum;
    int outputs = prepare(kernel, n, parameter, &checksum);
    for (int sample = 0; sample < 3; ++sample)
      for (int order = 0; order < 3; ++order) {
        int tune = (sample + order) % 3;
        reset_output(kernel, n, parameter, outputs);
        uint32_t warm = functions[kernel][tune](data, out, n, parameter);
        sink = warm;
        if (warm != checksum || !check_output(outputs)) return kernel + 1;
        reset_output(kernel, n, parameter, outputs);
        uint32_t total = 0;
        uint64_t start = cycles();
        /* Pointer output holds starting points: restore them between calls.
         * This small reset is common across tunes and included in timings. */
        for (int repeat = 0; repeat < 2; ++repeat) {
          if (kernel == 2 && repeat) reset_output(kernel, n, parameter, outputs);
          total += functions[kernel][tune](data, out, n, parameter);
        }
        measurements[c][tune][sample] = cycles() - start;
        sink = total;
        if (total != checksum * 2u || !check_output(outputs)) return kernel + 1;
      }
  }
  static char buffer[8192];
  setvbuf(stdout, buffer, _IOFBF, sizeof(buffer));
  for (int c = 0; c < 15; ++c)
    for (int tune = 0; tune < 3; ++tune) {
      printf("W %d %d %d %d", cases[c][0], cases[c][1], cases[c][2], tune);
      for (int s = 0; s < 3; ++s) printf(" %lu", (unsigned long)measurements[c][tune][s]);
      printf("\n");
    }
  printf("WORKLOADS_OK cases=15 repeats=2 samples=3\n");
  return 0;
}
