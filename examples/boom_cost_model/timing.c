/* Warm-cache, scalar microbenchmark comparison on a single BOOM hart.
 * Kernels are compiled separately: no LTO, and only their -mtune changes.
 * HOST_CHECK validates inputs/results without claiming host timings.
 */
#include <stdint.h>
#include <stdio.h>

#ifdef BENCH_SUITE
#define MAX_N 512
#define REPEATS 2
#define SAMPLES 3
#else
#define MAX_N 128
#define REPEATS 8
#define SAMPLES 6
#endif
#define DECLARE(t) \
  int branchy_##t(const int *, int); \
  int int_mix_##t(const int *, int); \
  float dot_##t(const float *, const float *, int); \
  void saxpy_##t(int, float, const float *, float *)
DECLARE(rocket);
DECLARE(generic_ooo);
DECLARE(xiangshan_nanhu);

static int values[MAX_N] __attribute__((aligned(64)));
static float x[MAX_N] __attribute__((aligned(64)));
static float y[MAX_N] __attribute__((aligned(64)));
static volatile int int_sink;
static volatile float float_sink;

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

static void reset_y(int n) {
  for (int i = 0; i < n; ++i) y[i] = (float)(i % 8) * 0.25f;
}

static int measure(int n, int pattern, uint64_t measurements[SAMPLES][3][4]) {
  int (*branch[])(const int *, int) = {branchy_rocket, branchy_generic_ooo, branchy_xiangshan_nanhu};
  int (*mix[])(const int *, int) = {int_mix_rocket, int_mix_generic_ooo, int_mix_xiangshan_nanhu};
  float (*dots[])(const float *, const float *, int) = {dot_rocket, dot_generic_ooo, dot_xiangshan_nanhu};
  void (*saxpys[])(int, float, const float *, float *) = {saxpy_rocket, saxpy_generic_ooo, saxpy_xiangshan_nanhu};
  int expected_branch = 0, expected_mix = 0;
  float expected_dot = 0;
  uint32_t state = 0x12345678;
  for (int i = 0; i < n; ++i) {
    int v = (i * 37) % 257 - 64;
    if (pattern == 1) v = i % 100;          /* All middle branch. */
    if (pattern == 2) v = 101 + i % 100;    /* All high branch. */
    if (pattern == 3) {
      state = state * 1664525u + 1013904223u;
      v = (int)((state >> 16) % 257) - 64;  /* Seeded mixed branches. */
    }
    values[i] = v;
    x[i] = (float)(i % 16 - 8) * 0.125f;
    expected_branch += v > 100 ? v * 3 : v < 0 ? -v : 1;
    expected_mix += (v * 13) / (v | 1);
    expected_dot += x[i] * ((float)(i % 8) * 0.25f);
  }
  for (int sample = 0; sample < SAMPLES; ++sample) {
    for (int order = 0; order < 3; ++order) {
      int t = (sample + order) % 3;
      int sum = 0;
      int_sink = branch[t](values, n);
      uint64_t start = cycles();
      for (int r = 0; r < REPEATS; ++r) sum += branch[t](values, n);
      measurements[sample][t][0] = cycles() - start;
      int_sink = sum;
      if (sum != expected_branch * REPEATS) return 1;

      sum = 0;
      int_sink = mix[t](values, n);
      start = cycles();
      for (int r = 0; r < REPEATS; ++r) sum += mix[t](values, n);
      measurements[sample][t][1] = cycles() - start;
      int_sink = sum;
      if (sum != expected_mix * REPEATS) return 2;

      reset_y(n);
      float total = 0;
      float_sink = dots[t](x, y, n);
      start = cycles();
      for (int r = 0; r < REPEATS; ++r) total += dots[t](x, y, n);
      measurements[sample][t][2] = cycles() - start;
      float_sink = total;
      if (total != expected_dot * REPEATS) return 3;

      saxpys[t](n, 1.5f, x, y);
      reset_y(n);
      start = cycles();
      for (int r = 0; r < REPEATS; ++r) saxpys[t](n, 1.5f, x, y);
      measurements[sample][t][3] = cycles() - start;
      for (int i = 0; i < n; ++i) {
        float expected = (float)(i % 8) * 0.25f + REPEATS * 1.5f * x[i];
        if (y[i] != expected) return 4;
      }
    }
  }
  return 0;
}

int main(void) {
#ifdef BENCH_SUITE
  const int sizes[] = {32, 128, 512};
  static uint64_t all[3][4][SAMPLES][3][4];
  for (int size = 0; size < 3; ++size)
    for (int pattern = 0; pattern < 4; ++pattern) {
      int error = measure(sizes[size], pattern, all[size][pattern]);
      if (error) return error;
    }
  /* Buffer output to avoid hundreds of slow HTIF console handshakes.
   * This storage is declared after measurement and is separate from inputs. */
  static char print_buffer[16384];
  setvbuf(stdout, print_buffer, _IOFBF, sizeof(print_buffer));
  for (int size = 0; size < 3; ++size)
    for (int pattern = 0; pattern < 4; ++pattern)
      for (int t = 0; t < 3; ++t)
        for (int k = 0; k < 4; ++k) {
          printf("S %d %d %d %d", sizes[size], pattern, k, t);
          for (int s = 0; s < SAMPLES; ++s)
            printf(" %lu", (unsigned long)all[size][pattern][s][t][k]);
          printf("\n");
        }
  printf("SUITE_OK sizes=32,128,512 patterns=4 repeats=2 samples=3\n");
#else
  uint64_t measurements[SAMPLES][3][4];
  int error = measure(128, 0, measurements);
  if (error) return error;
  /* Printing is outside every timed region and after all samples. */
  const char *names[] = {"rocket", "generic-ooo", "xiangshan-nanhu"};
  const char *kernels[] = {"branchy", "int_mix", "dot", "saxpy"};
  for (int s = 0; s < SAMPLES; ++s)
    for (int t = 0; t < 3; ++t)
      for (int k = 0; k < 4; ++k)
        printf("RESULT %s %s %d %lu\n", kernels[k], names[t], s,
               (unsigned long)measurements[s][t][k]);
  printf("CHECKS_OK n=128 repeats=%d samples=%d\n", REPEATS, SAMPLES);
#endif
  return 0;
}
