/* End-to-end timing driver (bare metal, HTIF console). Prints one line per (variant, kernel):
   E k=<variant>_<kernel> cyc=<warm>,<t1>,<t2> res=<hex>   and E-CHECK ok=<0|1> (all variants agree). */
typedef unsigned long u64; typedef long s64; typedef unsigned u32;
volatile u64 tohost __attribute__((section(".tohost"), aligned(64)));
volatile u64 fromhost __attribute__((section(".fromhost"), aligned(64)));
static volatile u64 sysbuf[8] __attribute__((aligned(64)));
static void htif_write(const char *s, u64 n) {
  sysbuf[0] = 64; sysbuf[1] = 1; sysbuf[2] = (u64)s; sysbuf[3] = n;
  __sync_synchronize(); fromhost = 0; tohost = (u64)sysbuf;
  while (fromhost == 0) {}
  fromhost = 0; __sync_synchronize();
}
static char buf[8192]; static unsigned bp;
static void ps(const char *s) { while (*s) buf[bp++] = *s++; }
static void pu(u64 v) { char t[24]; int i = 0; do { t[i++] = '0' + v % 10; v /= 10; } while (v); while (i) buf[bp++] = t[--i]; }
static void px(u64 v) { for (int i = 15; i >= 0; i--) { unsigned d = (v >> (4 * i)) & 15; buf[bp++] = d < 10 ? '0' + d : 'a' + d - 10; } }
static inline u64 rdcycle(void) { u64 v; asm volatile("rdcycle %0" : "=r"(v)); return v; }
#define DECL(p) \
  u32 p##e1_rec_mod100(u32, int); u64 p##e2_rec_mod1000(u64, int); u64 p##e3_rec_div1000(u64, int); \
  u64 p##e4_sum_mod10(const u64 *, int); u64 p##e5_hash(const unsigned char *, int); int p##e6_sneg_div13(int, int);
DECL(rk_) DECL(oo_) DECL(bs_) DECL(bo_)
static u64 A[64]; static unsigned char C[64];
#define N 64
#define T(name, expr) do { u64 c[3], r = 0; for (int k = 0; k < 3; k++) { u64 t0 = rdcycle(); r = (u64)(expr); c[k] = rdcycle() - t0; } \
  ps("E k=" name " cyc="); pu(c[0]); ps(","); pu(c[1]); ps(","); pu(c[2]); ps(" res="); px(r); ps("\n"); res[ri++] = r; } while (0)
#define V(p, pn) T(pn "_e1", p##e1_rec_mod100(12345, N)); T(pn "_e2", p##e2_rec_mod1000(777, N)); T(pn "_e3", p##e3_rec_div1000(999, N)); \
  T(pn "_e4", p##e4_sum_mod10(A, N)); T(pn "_e5", p##e5_hash(C, N)); T(pn "_e6", p##e6_sneg_div13(4321, N));
int main(void) {
  u64 res[64]; int ri = 0;
  u64 s = 0x9e3779b97f4a7c15ULL;
  for (int i = 0; i < N; i++) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; A[i] = s; C[i] = (unsigned char)s; }
  u64 marchid; asm volatile("csrr %0, marchid" : "=r"(marchid));
  ps("E-BEGIN marchid="); pu(marchid); ps(" n="); pu(N); ps("\n");
  T("empty", 0);
  V(rk_, "rocket") V(oo_, "ooo") V(bs_, "sel-rocket") V(bo_, "sel-ooo")
  int ok = 1;
  for (int v = 1; v < 4; v++) for (int k = 0; k < 6; k++) if (res[1 + v * 6 + k] != res[1 + k]) ok = 0;
  ps("E-CHECK ok="); pu(ok); ps("\n");
  htif_write(buf, bp);
  return ok ? 0 : 3;
}
