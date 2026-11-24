/* rtl-kernels driver: for each (kernel entry, compiler variant) one warmup
   call and RK_REPS timed calls; the entry times its own region with
   rdcycle/rdinstret.  Prints one "RK ..." line per entry via HTIF. */
#include "rk.h"
#ifndef RK_REPS
#define RK_REPS 2
#endif
typedef struct { const char *k; const char *v; u64 (*fn)(u64 *); u64 expect; } ent_t;
extern const ent_t RK_TAB[];
extern const unsigned RK_N;
extern const char RK_GROUP[];

volatile u64 tohost __attribute__((section(".tohost"), aligned(64)));
volatile u64 fromhost __attribute__((section(".fromhost"), aligned(64)));
static volatile u64 sysbuf[8] __attribute__((aligned(64)));

void *memcpy(void *d, const void *s, size_t n) { char *a = d; const char *b = s; while (n--) *a++ = *b++; return d; }
void *memset(void *d, int c, size_t n) { char *a = d; while (n--) *a++ = (char)c; return d; }
void *memmove(void *d, const void *s, size_t n) {
  char *a = d; const char *b = s;
  if (a < b) while (n--) *a++ = *b++; else { a += n; b += n; while (n--) *--a = *--b; }
  return d;
}

static void htif_write(const char *s, u64 n) {
  sysbuf[0] = 64; sysbuf[1] = 1; sysbuf[2] = (u64)s; sysbuf[3] = n;
  __sync_synchronize();
  fromhost = 0;
  tohost = (u64)sysbuf;
  while (fromhost == 0) {}
  fromhost = 0;
  __sync_synchronize();
}
static char line[8192];
static u32 lp;
static void ps(const char *s) { while (*s && lp < sizeof(line) - 2) line[lp++] = *s++; }
static void pu(u64 v) { char t[24]; int i = 0; do { t[i++] = '0' + (char)(v % 10); v /= 10; } while (v); while (i && lp < sizeof(line) - 2) line[lp++] = t[--i]; }
static void px(u64 v) { for (int i = 15; i >= 0; i--) { unsigned d = (unsigned)(v >> (4 * i)) & 15; line[lp++] = (char)(d < 10 ? '0' + d : 'a' + d - 10); } }
static void drain(void) { if (lp) { htif_write(line, lp); lp = 0; } }
static void nl(void) { line[lp++] = '\n'; if (lp > 6000) drain(); }

int main(void) {
  u64 t0 = rk_cyc();
  unsigned pass = 0, fail = 0;
  u64 marchid;
  __asm__ volatile("csrr %0, marchid" : "=r"(marchid));
  rk_data_init();
  ps("RK-BEGIN group="); ps(RK_GROUP); ps(" n="); pu(RK_N); ps(" reps="); pu(RK_REPS);
  ps(" marchid="); pu(marchid); ps(" init_cyc="); pu(rk_cyc() - t0); nl();
  drain();
  for (unsigned e = 0; e < RK_N; e++) {
    const ent_t *E = &RK_TAB[e];
    u64 tm[2], cyc[RK_REPS], ins[RK_REPS], s;
    int ok = 1;
    s = E->fn(tm);
    if (s != E->expect) ok = 0;
    for (int r = 0; r < RK_REPS; r++) {
      s = E->fn(tm);
      cyc[r] = tm[0]; ins[r] = tm[1];
      if (s != E->expect) ok = 0;
    }
    if (ok) pass++; else fail++;
    ps("RK k="); ps(E->k); ps(" v="); ps(E->v); ps(" cyc=");
    for (int r = 0; r < RK_REPS; r++) { if (r) ps(","); pu(cyc[r]); }
    ps(" ins=");
    for (int r = 0; r < RK_REPS; r++) { if (r) ps(","); pu(ins[r]); }
    ps(" sum="); px(s); ps(" exp="); px(E->expect); ps(" ok="); pu(ok); nl();
  }
  ps("RK-END group="); ps(RK_GROUP); ps(" pass="); pu(pass); ps(" fail="); pu(fail);
  ps(" total_cycles="); pu(rk_cyc() - t0); nl();
  drain();
  return fail ? 2 : 0;
}
