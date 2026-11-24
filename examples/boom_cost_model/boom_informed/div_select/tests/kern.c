/* boom_div_select test kernels: range shapes x dependency shapes */
typedef unsigned long u64; typedef long s64; typedef unsigned u32;
/* 1: varying dividend, independent (throughput) */
u64 k_sum_mod10(const u64 *a, int n) { u64 s = 0; for (int i = 0; i < n; i++) s += a[i] % 10; return s; }
/* 2: recurrence with range [256,511] mod 100 (u32) */
u32 k_rec_mod100(u32 x, int n) { for (int i = 0; i < n; i++) x = ((x % 100) & 255) | 256; return x; }
/* 3: recurrence varying (hash) */
u64 k_hash(const unsigned char *p, int n) { u64 h = 0; for (int i = 0; i < n; i++) h = (h * 31 + p[i]) % 1000003; return h; }
/* 4: guarded range [100,1599] */
u32 k_guard_div(u32 x) { if (x >= 100 && x < 1600) return x / 100; return 0; }
u32 k_guard_mod(u32 x) { if (x >= 100 && x < 1600) return x % 100; return 0; }
/* 5: signed, range [-1599,-100] */
int k_sneg_mod(int x) { if (x <= -100 && x > -1600) return x % 13; return 0; }
/* 6: range admits 0: [0,255] */
u32 k_byte_div(unsigned char c) { return c / 10; }
/* 7: 64-bit recurrence, small quotient: x in [2^20, 2^21) */
u64 k_rec64(u64 x, int n) { for (int i = 0; i < n; i++) x = ((x / 7) & 0xfffff) | 0x100000; return x; }
/* 8: two divides in a long throughput loop body */
s64 k_two(const s64 *a, const s64 *b, int n) { s64 s = 0; for (int i = 0; i < n; i++) { s64 x = (a[i] & 1023) | 1024, y = (b[i] & 1023) | 1024; s += x / 1000 + y % 1000 + a[i] * b[i] + (a[i] ^ b[i]) + (a[i] >> 3) + (b[i] << 2); } return s; }
/* 2b/7b: recurrences with in-range initial values */
u32 k_rec_mod100b(u32 x0, int n) { u32 x = (x0 & 255) | 256; for (int i = 0; i < n; i++) x = ((x % 100) & 255) | 256; return x; }
u64 k_rec64b(u64 x0, int n) { u64 x = (x0 & 0xfffff) | 0x100000; for (int i = 0; i < n; i++) x = ((x / 7) & 0xfffff) | 0x100000; return x; }
