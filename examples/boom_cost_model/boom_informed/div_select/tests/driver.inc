/* Shared driver for gen_correct.py shards (QEMU user mode). */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
enum { K_U64, K_S64, K_U32, K_S32, K_U16, K_S16, K_U8, K_S8 };
struct ent { int kind; void *f, *r; long long d; const char *name; };
#define T_u64(f, r, d, n) { K_U64, (void *)f, (void *)r, (long long)(d), n }
#define T_s64(f, r, d, n) { K_S64, (void *)f, (void *)r, (long long)(d), n }
#define T_u32(f, r, d, n) { K_U32, (void *)f, (void *)r, (long long)(d), n }
#define T_s32(f, r, d, n) { K_S32, (void *)f, (void *)r, (long long)(d), n }
#define T_u16(f, r, d, n) { K_U16, (void *)f, (void *)r, (long long)(d), n }
#define T_s16(f, r, d, n) { K_S16, (void *)f, (void *)r, (long long)(d), n }
#define T_u8(f, r, d, n) { K_U8, (void *)f, (void *)r, (long long)(d), n }
#define T_s8(f, r, d, n) { K_S8, (void *)f, (void *)r, (long long)(d), n }

static uint64_t rs = 0x9e3779b97f4a7c15ULL;
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }

static unsigned long long nchk, nfail;

#define CHECK(T, F, R, X)                                                    \
  do {                                                                       \
    T x_ = (T)(X);                                                           \
    if (sizeof(T) == 8 && (T)-1 < 0 && x_ == (T)INT64_MIN && e->d == -1) break; \
    T a_ = ((T(*)(T))(F))(x_), b_ = ((T(*)(T))(R))(x_);                     \
    nchk++;                                                                  \
    if (a_ != b_) {                                                          \
      if (nfail++ < 20)                                                      \
        printf("FAIL %s x=%lld got=%lld exp=%lld\n", e->name, (long long)x_, \
               (long long)a_, (long long)b_);                                \
    }                                                                        \
  } while (0)

static void one(const struct ent *e, uint64_t x) {
  switch (e->kind) {
  case K_U64: CHECK(uint64_t, e->f, e->r, x); break;
  case K_S64: CHECK(int64_t, e->f, e->r, x); break;
  case K_U32: CHECK(uint32_t, e->f, e->r, x); break;
  case K_S32: CHECK(int32_t, e->f, e->r, x); break;
  case K_U16: CHECK(uint16_t, e->f, e->r, x); break;
  case K_S16: CHECK(int16_t, e->f, e->r, x); break;
  case K_U8: CHECK(uint8_t, e->f, e->r, x); break;
  case K_S8: CHECK(int8_t, e->f, e->r, x); break;
  }
}

static int run(const struct ent *E, unsigned n, long nrand) {
  for (unsigned i = 0; i < n; i++) {
    const struct ent *e = &E[i];
    long long d = e->d;
    uint64_t ed[] = {0, 1, 2, 3, (uint64_t)-1, (uint64_t)-2, INT64_MAX, (uint64_t)INT64_MIN,
                     (uint64_t)INT64_MIN + 1, UINT32_MAX, INT32_MAX, (uint64_t)INT32_MIN,
                     0x8000, 0x7fff, 0xffff, 0x80, 0x7f, 0xff};
    for (unsigned k = 0; k < sizeof ed / sizeof ed[0]; k++) one(e, ed[k]);
    for (long m = -4; m <= 4; m++)
      for (long q = -2; q <= 2; q++) one(e, (uint64_t)(m * d + q));
    for (int k = 0; k < 64; k++) {
      uint64_t p = 1ULL << k;
      one(e, p); one(e, p - 1); one(e, p + 1); one(e, -p); one(e, -p + 1); one(e, -p - 1);
    }
    for (long k = 0; k < nrand; k++) {
      uint64_t r = rnd();
      switch (k & 3) {
      case 0: one(e, r); break;
      case 1: one(e, r >> (r & 63)); break;          /* all magnitudes */
      case 2: one(e, -(r >> (r & 63))); break;
      case 3: one(e, (uint64_t)d * (r & 0xffff) + (r >> 60) - 8); break;  /* near multiples */
      }
    }
  }
  printf("checks=%llu failures=%llu functions=%u\n", nchk, nfail, n);
  return nfail != 0;
}
