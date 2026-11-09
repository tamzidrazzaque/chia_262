#include <stdint.h>
/* Constant divisor chosen so GCC may expand to mulh magic or keep div. */
__attribute__((noinline)) uint64_t udiv_const(uint64_t x) {
  return x / 13u;
}
__attribute__((noinline)) int64_t sdiv_const(int64_t x) {
  return x / 13;
}
__attribute__((noinline)) uint64_t udiv_var(uint64_t x, uint64_t y) {
  return x / y;
}
__attribute__((noinline)) uint64_t urem_var(uint64_t x, uint64_t y) {
  return x % y;
}
/* Force hardware div via asm for measurement scaffolding */
__attribute__((noinline)) uint64_t force_div(uint64_t x, uint64_t y) {
  uint64_t q;
  asm volatile("divu %0, %1, %2" : "=r"(q) : "r"(x), "r"(y));
  return q;
}
__attribute__((noinline)) uint64_t force_mulh_magic(uint64_t x) {
  /* approximate reciprocal multiply for /13 using mulhu + shifts (illustrative) */
  uint64_t hi;
  const uint64_t M = 0x4EC4EC4EC4EC4EC5ULL; /* example magic; correctness secondary to latency shape */
  asm volatile("mulhu %0, %1, %2" : "=r"(hi) : "r"(x), "r"(M));
  return hi >> 2;
}
