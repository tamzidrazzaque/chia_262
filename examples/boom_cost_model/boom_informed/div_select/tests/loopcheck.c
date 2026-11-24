/* Compares kern.c compiled without (k_*) and with the plugin (p_k_*). */
#include <stdio.h>
#include <stdint.h>
typedef unsigned long u64; typedef long s64; typedef unsigned u32;
#define DECL(p) \
 u64 p##k_sum_mod10(const u64 *, int); u32 p##k_rec_mod100(u32, int); u64 p##k_hash(const unsigned char *, int); \
 u32 p##k_guard_div(u32); u32 p##k_guard_mod(u32); int p##k_sneg_mod(int); u32 p##k_byte_div(unsigned char); \
 u64 p##k_rec64(u64, int); s64 p##k_two(const s64 *, const s64 *, int); u32 p##k_rec_mod100b(u32, int); u64 p##k_rec64b(u64, int);
DECL() DECL(p_)
static uint64_t rs = 88172645463325252ULL;
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }
static u64 A[512]; static s64 B[512]; static unsigned char C[512];
int main(void) {
  unsigned long fails = 0, n = 0;
  for (int it = 0; it < 20000; it++) {
    for (int i = 0; i < 64; i++) { A[i] = rnd() >> (rnd() & 63); B[i] = (s64)rnd() >> (rnd() & 63); C[i] = rnd(); }
    u64 x = rnd() >> (rnd() & 63); int len = rnd() & 63;
#define CK(e1, e2) do { n++; if ((e1) != (e2)) { if (fails++ < 10) printf("FAIL line %d it %d\n", __LINE__, it); } } while (0)
    CK(k_sum_mod10(A, len), p_k_sum_mod10(A, len));
    CK(k_rec_mod100(x, len), p_k_rec_mod100(x, len));
    CK(k_hash(C, len), p_k_hash(C, len));
    CK(k_guard_div(x), p_k_guard_div(x)); CK(k_guard_mod(x), p_k_guard_mod(x));
    CK(k_guard_div(x & 2047), p_k_guard_div(x & 2047)); CK(k_guard_mod(x & 2047), p_k_guard_mod(x & 2047));
    CK(k_sneg_mod((int)x), p_k_sneg_mod((int)x)); CK(k_sneg_mod(-(int)(x & 2047)), p_k_sneg_mod(-(int)(x & 2047)));
    CK(k_byte_div(x), p_k_byte_div(x));
    CK(k_rec64(x, len), p_k_rec64(x, len)); CK(k_two(B, (s64 *)A, len), p_k_two(B, (s64 *)A, len));
    CK(k_rec_mod100b(x, len), p_k_rec_mod100b(x, len)); CK(k_rec64b(x, len), p_k_rec64b(x, len));
  }
  printf("loopcheck checks=%lu failures=%lu\n", n, fails);
  return fails != 0;
}
