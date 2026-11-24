/* rtl-tune bare-metal harness: fills inputs, times each kernel with rdcycle /
   rdinstret around a call into the separately compiled kernel TU.
   One warmup call + REPS timed calls. Output via HTIF write syscall.
   Compiled by ONE fixed compiler for all variants. */
typedef unsigned long long u64;
typedef unsigned int u32;
typedef int s32;
#define N 256
#define NL 128
#ifndef REPS
#define REPS 2
#endif
struct node { struct node *next; u32 v; u32 d; s32 t; u32 pad; };
u64 A64[N], B64[N], C64[N], OUT64[N];
u32 IDX[N];
s32 S32[N];
double DX[N], DY[N];
struct node NODES[NL];
struct node *HEAD;

u64 k_mul_load(void), k_mul_stream(void), k_chase_divvar(void), k_chase_divconst(void),
    k_divconst_arr(void), k_fma_horner(void), k_fma_dot(void), k_alu4_mul(void), k_mulconst(void);
static const struct { const char *name; u64 (*fn)(void); } K[] = {
  {"mul_load", k_mul_load}, {"mul_stream", k_mul_stream}, {"chase_divvar", k_chase_divvar},
  {"chase_divconst", k_chase_divconst}, {"divconst_arr", k_divconst_arr},
  {"fma_horner", k_fma_horner}, {"fma_dot", k_fma_dot}, {"alu4_mul", k_alu4_mul},
  {"mulconst", k_mulconst}};

volatile u64 tohost __attribute__((section(".tohost"), aligned(64)));
volatile u64 fromhost __attribute__((section(".fromhost"), aligned(64)));
static volatile u64 sysbuf[8] __attribute__((aligned(64)));
static void htif_write(const char *s, u64 n) {
  sysbuf[0] = 64; sysbuf[1] = 1; sysbuf[2] = (u64)s; sysbuf[3] = n;
  __sync_synchronize(); fromhost = 0; tohost = (u64)sysbuf;
  while (fromhost == 0) { }
  fromhost = 0; __sync_synchronize();
}
static char line[4096]; static u32 lp;
static void ps(const char *s) { while (*s && lp < sizeof(line) - 2) line[lp++] = *s++; }
static void pu(u64 v) { char t[24]; int i = 0; do { t[i++] = '0' + (char)(v % 10); v /= 10; } while (v);
  while (i) line[lp++] = t[--i]; }
static void px(u64 v) { for (int i = 15; i >= 0; i--) { unsigned d = (unsigned)(v >> (4 * i)) & 15;
  line[lp++] = (char)(d < 10 ? '0' + d : 'a' + d - 10); } }
static void nl(void) { line[lp++] = '\n'; if (lp > 3000) { htif_write(line, lp); lp = 0; } }
static inline u64 rdcycle(void) { u64 v; asm volatile("rdcycle %0" : "=r"(v)); return v; }
static inline u64 rdinstret(void) { u64 v; asm volatile("rdinstret %0" : "=r"(v)); return v; }

static u64 st = 0x243F6A8885A308D3ULL;
static u64 rnd(void) { st ^= st << 13; st ^= st >> 7; st ^= st << 17; return st; }

int main(void) {
  u64 t0 = rdcycle();
  for (int i = 0; i < N; i++) {
    A64[i] = rnd(); B64[i] = rnd(); C64[i] = rnd();
    IDX[i] = (u32)(rnd() % N);
    S32[i] = (s32)(rnd() & 0x7fffffff) - 0x40000000;          /* signed, full 31-bit range */
    DX[i] = (double)(rnd() % 2001) / 1000.0 - 1.0;             /* [-1, 1] */
  }
  /* shuffled singly linked list over NODES */
  u32 perm[NL];
  for (u32 i = 0; i < NL; i++) perm[i] = i;
  for (u32 i = NL - 1; i > 0; i--) { u32 j = (u32)(rnd() % (i + 1)); u32 t = perm[i]; perm[i] = perm[j]; perm[j] = t; }
  for (u32 i = 0; i < NL; i++) {
    struct node *n = &NODES[perm[i]];
    n->next = i + 1 < NL ? &NODES[perm[i + 1]] : 0;
    n->v = (u32)rnd(); n->d = 1 + (u32)(rnd() % 1000);
    n->t = (s32)(rnd() % (86400u * 7));
  }
  HEAD = &NODES[perm[0]];
  for (int i = 0; i < N; i++) DY[i] = DX[(i * 7) % N];
  ps("RT-BEGIN n="); pu(sizeof K / sizeof K[0]); ps(" reps="); pu(REPS); ps(" init_cycles="); pu(rdcycle() - t0); nl();
  for (unsigned k = 0; k < sizeof K / sizeof K[0]; k++) {
    u64 cyc[REPS], ins[REPS], sum[REPS + 1];
    sum[0] = K[k].fn();                     /* warmup */
    for (int r = 0; r < REPS; r++) {
      u64 c0 = rdcycle(), i0 = rdinstret();
      sum[r + 1] = K[k].fn();
      u64 i1 = rdinstret(), c1 = rdcycle();
      cyc[r] = c1 - c0; ins[r] = i1 - i0;
    }
    ps("RT k="); ps(K[k].name); ps(" cyc=");
    for (int r = 0; r < REPS; r++) { if (r) ps(","); pu(cyc[r]); }
    ps(" ins=");
    for (int r = 0; r < REPS; r++) { if (r) ps(","); pu(ins[r]); }
    ps(" sum="); px(sum[REPS]); ps(" sum0="); px(sum[0]); nl();
  }
  ps("RT-END total_cycles="); pu(rdcycle() - t0); nl();
  htif_write(line, lp);
  return 0;
}
