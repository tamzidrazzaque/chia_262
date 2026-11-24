/* End-to-end kernels: compiled by stock GCC 15.1 (rocket / generic-ooo tune) and with boom_div_select. */
typedef unsigned long u64; typedef long s64; typedef unsigned u32;
/* e1: u32 recurrence, dividend in [256,511], % 100 */
u32 e1_rec_mod100(u32 x0, int n) { u32 x = (x0 & 255) | 256; for (int i = 0; i < n; i++) x = ((x % 100) * 7 & 255) | 256; return x; }
/* e2: u64 recurrence, dividend in [1024,2047], % 1000 */
u64 e2_rec_mod1000(u64 x0, int n) { u64 x = (x0 & 1023) | 1024; for (int i = 0; i < n; i++) x = ((x % 1000) * 5 & 1023) | 1024; return x; }
/* e3: u64 recurrence, dividend in [1024,2047], / 1000 (quotient 1 or 2) */
u64 e3_rec_div1000(u64 x0, int n) { u64 x = (x0 & 1023) | 1024; for (int i = 0; i < n; i++) x = ((x / 1000) * 517 + x) & 1023 | 1024; return x; }
/* e4: throughput, varying dividends, % 10 */
u64 e4_sum_mod10(const u64 *a, int n) { u64 s = 0; for (int i = 0; i < n; i++) s += a[i] % 10; return s; }
/* e5: latency, varying (hash) % 1000003 */
u64 e5_hash(const unsigned char *p, int n) { u64 h = 0; for (int i = 0; i < n; i++) h = (h * 31 + p[i]) % 1000003; return h; }
/* e6: s32 recurrence with small negative dividends in [-1023,-512], / 13 */
int e6_sneg_div13(int x0, int n) { int x = -((x0 & 511) | 512); for (int i = 0; i < n; i++) x = -(((-(x / 13) * 29) & 511) | 512); return x; }
