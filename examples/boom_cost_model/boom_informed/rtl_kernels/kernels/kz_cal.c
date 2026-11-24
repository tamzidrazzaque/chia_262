/* Calibration: single-precision fdiv.s / fsqrt.s latency and throughput, to
   check the rtl-model FP div/sqrt numbers (derived for double; the model
   assumes single runs the same algorithm). 64 ops per entry. */
#include "rk.h"
#ifdef __riscv
/* straight-line .rept blocks keep the value in an FP register (a C loop let
   GCC bounce it through an integer register: fmv.s.x/fmv.x.s per op) */
#define R64_1(ins) __asm__ volatile(".rept 64\n " ins " %0, %0, %1\n .endr" : "+f"(x) : "f"(y))
#define R16_4(ins) __asm__ volatile(".rept 16\n " ins " %0,%0,%4\n " ins " %1,%1,%4\n " ins " %2,%2,%4\n " ins " %3,%3,%4\n .endr" : "+f"(a), "+f"(b), "+f"(c), "+f"(d) : "f"(y))
#define S64_1() __asm__ volatile(".rept 64\n fsqrt.s %0, %0\n .endr" : "+f"(x))
#define S16_4() __asm__ volatile(".rept 16\n fsqrt.s %0,%0\n fsqrt.s %1,%1\n fsqrt.s %2,%2\n fsqrt.s %3,%3\n .endr" : "+f"(a), "+f"(b), "+f"(c), "+f"(d))
#else
#define R64_1(ins) do { for (int i = 0; i < 64; i++) x = x / y; } while (0)
#define R16_4(ins) do { for (int i = 0; i < 16; i++) { a /= y; b /= y; c /= y; d /= y; } } while (0)
#define S64_1() do { for (int i = 0; i < 64; i++) x = __builtin_sqrtf(x); } while (0)
#define S16_4() do { for (int i = 0; i < 16; i++) { a = __builtin_sqrtf(a); b = __builtin_sqrtf(b); c = __builtin_sqrtf(c); d = __builtin_sqrtf(d); } } while (0)
#endif
static u64 fb(float f) { union { float f; u32 u; } c; c.f = f; return c.u; }
static u64 db(double f) { union { double f; u64 u; } c; c.f = f; return c.u; }
static volatile float vy = 1.0001f, vx = 12345.678f, vs = 3.0e30f;
static volatile double vyd = 1.0001;

u64 F(cal_fdivs_dep)(u64 *tm) {
  float x = vx, y = vy;
  TSTART(tm);
  R64_1("fdiv.s");
  TSTOP(tm);
  return fb(x);
}
u64 F(cal_fdivs_ind4)(u64 *tm) {
  float a = vx, b = vx + 1, c = vx + 2, d = vx + 3, y = vy;
  TSTART(tm);
  R16_4("fdiv.s");
  TSTOP(tm);
  return fb(a) ^ fb(b) ^ fb(c) ^ fb(d);
}
u64 F(cal_fsqrts_dep)(u64 *tm) {
  float x = vs;
  TSTART(tm);
  S64_1();
  TSTOP(tm);
  return fb(x);
}
u64 F(cal_fsqrts_ind4)(u64 *tm) {
  float a = vs, b = vs * 2, c = vs * 3, d = vs * 4;
  TSTART(tm);
  S16_4();
  TSTOP(tm);
  return fb(a) ^ fb(b) ^ fb(c) ^ fb(d);
}
u64 F(cal_fdivd_dep)(u64 *tm) {
  double x = 12345.678, y = vyd;
  TSTART(tm);
  R64_1("fdiv.d");
  TSTOP(tm);
  return db(x);
}
u64 F(cal_empty)(u64 *tm) {
  TSTART(tm);
  TSTOP(tm);
  return 1;
}
