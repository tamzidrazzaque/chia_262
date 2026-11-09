/* Directed BOOM probe: dependent/independent mulhu vs divu/rem.
 *
 * Compile with the RISC-V bare-metal or Linux toolchain used for BOOM
 * Verilator / FireSim guests. Time with mcycle. This file is the next
 * measurement step once a BOOM execution environment is available.
 *
 * Not a SPEC workload. Do not treat host/QEMU wall time as BOOM performance.
 */
#include <stdint.h>
#include <stdio.h>

static inline uint64_t rdcycle(void) {
  uint64_t v;
  asm volatile("rdcycle %0" : "=r"(v));
  return v;
}

#define N 512

__attribute__((noinline)) uint64_t dep_divu(uint64_t x, uint64_t d) {
  uint64_t a = x;
  for (int i = 0; i < N; i++)
    asm volatile("divu %0, %1, %2" : "=r"(a) : "r"(a), "r"(d));
  return a;
}

__attribute__((noinline)) uint64_t dep_mulhu(uint64_t x, uint64_t m) {
  uint64_t a = x;
  for (int i = 0; i < N; i++)
    asm volatile("mulhu %0, %1, %2" : "=r"(a) : "r"(a), "r"(m));
  return a;
}

__attribute__((noinline)) uint64_t indep_divu(uint64_t x0, uint64_t d) {
  uint64_t a0 = x0, a1 = x0 + 1, a2 = x0 + 2, a3 = x0 + 3;
  for (int i = 0; i < N / 4; i++) {
    asm volatile("divu %0, %1, %2" : "=r"(a0) : "r"(a0), "r"(d));
    asm volatile("divu %0, %1, %2" : "=r"(a1) : "r"(a1), "r"(d));
    asm volatile("divu %0, %1, %2" : "=r"(a2) : "r"(a2), "r"(d));
    asm volatile("divu %0, %1, %2" : "=r"(a3) : "r"(a3), "r"(d));
  }
  return a0 ^ a1 ^ a2 ^ a3;
}

__attribute__((noinline)) uint64_t indep_mulhu(uint64_t x0, uint64_t m) {
  uint64_t a0 = x0, a1 = x0 + 1, a2 = x0 + 2, a3 = x0 + 3;
  for (int i = 0; i < N / 4; i++) {
    asm volatile("mulhu %0, %1, %2" : "=r"(a0) : "r"(a0), "r"(m));
    asm volatile("mulhu %0, %1, %2" : "=r"(a1) : "r"(a1), "r"(m));
    asm volatile("mulhu %0, %1, %2" : "=r"(a2) : "r"(a2), "r"(m));
    asm volatile("mulhu %0, %1, %2" : "=r"(a3) : "r"(a3), "r"(m));
  }
  return a0 ^ a1 ^ a2 ^ a3;
}

static void bench(const char *name, uint64_t (*fn)(uint64_t, uint64_t),
                  uint64_t a, uint64_t b) {
  (void)fn(a, b); /* warmup */
  uint64_t t0 = rdcycle();
  uint64_t sink = fn(a, b);
  uint64_t t1 = rdcycle();
  printf("%s cycles=%llu sink=%llu\n", name,
         (unsigned long long)(t1 - t0), (unsigned long long)sink);
}

int main(void) {
  const uint64_t magic = 0x4EC4EC4EC4EC4EC5ULL;
  bench("dep_divu", dep_divu, 123456789ull, 13ull);
  bench("dep_mulhu", dep_mulhu, 123456789ull, magic);
  bench("indep_divu", indep_divu, 123456789ull, 13ull);
  bench("indep_mulhu", indep_mulhu, 123456789ull, magic);
  return 0;
}
