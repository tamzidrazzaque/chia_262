/* Scheduling-sensitive bare-metal kernels (written from scratch for rtl-tune).
   Compiled by each variant compiler (A/B/C/base); the harness (harness.c) is
   compiled once by a fixed compiler and is identical in every ELF.
   Every kernel reads global inputs filled by the harness and returns a
   64-bit checksum so that results can be compared across compilers. */
typedef unsigned long long u64;
typedef long long s64;
typedef unsigned int u32;
typedef int s32;

#define N 256
#define NL 128

struct node { struct node *next; u32 v; u32 d; s32 t; u32 pad; };

extern u64 A64[N], B64[N], C64[N], OUT64[N];
extern u32 IDX[N];
extern s32 S32[N];
extern double DX[N], DY[N];
extern struct node *HEAD;

/* 1. loop-carried multiply chain (FNV-style) mixed with indirect loads and
      an independent multiply-accumulate. */
u64 k_mul_load(void)
{
  u64 h = 1469598103934665603ULL, s = 0;
  for (int i = 0; i < N; i++) {
    u64 v = A64[IDX[i]];
    h = (h ^ v) * 1099511628211ULL;
    s += v * B64[i];
  }
  return h ^ s;
}

/* 2. independent multiplies per element feeding loads/stores (mul + load mix,
      throughput bound; schedule decides how muls and loads interleave). */
u64 k_mul_stream(void)
{
  u64 s = 0;
  for (int i = 0; i < N; i++) {
    u64 x = A64[i] * B64[i];
    u64 y = C64[i] * (x >> 17);
    OUT64[i] = y + x;
    s ^= y;
  }
  return s;
}

/* 3. pointer chase with a runtime divisor (div cannot be strength-reduced). */
u64 k_chase_divvar(void)
{
  u64 s = 0;
  for (const struct node *p = HEAD; p; p = p->next)
    s += p->v / p->d + p->v % p->d;
  return s;
}

/* 4. pointer chase with signed 32-bit divisions by constants
      (seconds -> days/hours/minutes); int_div cost decides div vs mulh. */
u64 k_chase_divconst(void)
{
  s64 s = 0;
  for (const struct node *p = HEAD; p; p = p->next) {
    s32 t = p->t;
    s32 days = t / 86400;
    s32 hours = (t / 3600) % 24;
    s32 mins = (t / 60) % 60;
    s += days * 1000000 + hours * 10000 + mins * 100 + t % 60;
  }
  return (u64)s;
}

/* 5. array of signed ints: divisions by small constants, no pointer chase. */
u64 k_divconst_arr(void)
{
  s64 s = 0;
  for (int i = 0; i < N; i++) {
    s32 x = S32[i];
    s += x / 10 + x / 7 + x % 9;
  }
  return (u64)s;
}

/* 6. independent Horner polynomials (FP fma, throughput bound). */
u64 k_fma_horner(void)
{
  double acc = 0.0;
  for (int i = 0; i < N; i++) {
    double x = DX[i];
    double y = 0.0078125;
    y = y * x + 0.125;
    y = y * x - 0.25;
    y = y * x + 0.5;
    y = y * x - 1.0;
    y = y * x + 2.0;
    DY[i] = y;
  }
  for (int i = 0; i < N; i += 8) acc += DY[i];
  union { double d; u64 u; } c = { acc };
  return c.u;
}

/* 7. FP dot product with two accumulators (latency bound fma chains). */
u64 k_fma_dot(void)
{
  double s0 = 0.0, s1 = 0.0;
  for (int i = 0; i < N; i += 2) {
    s0 += DX[i] * DY[i];
    s1 += DX[i + 1] * DY[i + 1];
  }
  union { double d; u64 u; } c = { s0 + s1 };
  return c.u;
}

/* 8. 4-wide ALU-bound mixing loop with one multiply per element. */
u64 k_alu4_mul(void)
{
  u64 s0 = 0, s1 = 0;
  for (int i = 0; i < N; i++) {
    u64 t = A64[i];
    u64 u = B64[i];
    t ^= t >> 7;
    u += u << 3;
    t += u ^ (t << 11);
    u ^= t >> 13;
    s0 += (t | 5) * 0x9E3779B97F4A7C15ULL;
    s1 += u - (t >> 3);
  }
  return s0 ^ s1;
}

/* 9. multiplies by small constants (synth_mult: mul vs shift/add). */
u64 k_mulconst(void)
{
  u64 s = 0;
  for (int i = 0; i < N; i++)
    s += A64[i] * 37 + B64[i] * 100 + C64[i] * 1000 + (u64)S32[i] * 11;
  return s;
}
