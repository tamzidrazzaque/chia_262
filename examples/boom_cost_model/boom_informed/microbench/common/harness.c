/* Generic driver: one warmup + MB_REPS timed calls per kernel.
   Each kernel times its own body with rdcycle/rdinstret (BOOM decodes
   CSRRS as unique + flush-on-commit, so the reads serialize; the fixed
   serialization overhead is measured by the ctl_empty kernel and subtracted
   by parse.py).  Output: one "MB k=..." line per kernel via HTIF write. */
typedef unsigned long long u64;
typedef unsigned int u32;

#ifndef MB_REPS
#define MB_REPS 3
#endif

typedef struct {
  const char *name;
  void (*fn)(const u64 *in, u64 *out, u64 *t);
  const u64 *in;
  u32 nout;
  u32 ops;
  u64 expect;
} kern_t;

extern const kern_t KERNELS[];
extern const unsigned NKERNELS;
extern const char GROUP[];

volatile u64 tohost __attribute__((section(".tohost"), aligned(64)));
volatile u64 fromhost __attribute__((section(".fromhost"), aligned(64)));

static volatile u64 sysbuf[8] __attribute__((aligned(64)));

static void htif_write(const char *s, u64 n) {
  sysbuf[0] = 64; /* SYS_write */
  sysbuf[1] = 1;
  sysbuf[2] = (u64)s;
  sysbuf[3] = n;
  __sync_synchronize();
  fromhost = 0;
  tohost = (u64)sysbuf;
  while (fromhost == 0) {
  }
  fromhost = 0;
  __sync_synchronize();
}

/* Output is buffered and sent in chunks: each HTIF syscall costs a host
   round trip (TSI on Verilator), so fewer, larger writes are cheaper.
   Build with -DMB_CHUNK=1 to write every line immediately. */
#ifndef MB_CHUNK
#define MB_CHUNK 4096
#endif
static char line[MB_CHUNK + 512];
static u32 lp;
static void ps(const char *s) { while (*s && lp < sizeof(line) - 2) line[lp++] = *s++; }
static void pu(u64 v) {
  char t[24];
  int i = 0;
  do { t[i++] = '0' + (char)(v % 10); v /= 10; } while (v);
  while (i && lp < sizeof(line) - 2) line[lp++] = t[--i];
}
static void px(u64 v) {
  for (int i = 15; i >= 0; i--) {
    unsigned d = (unsigned)(v >> (4 * i)) & 15;
    if (lp < sizeof(line) - 2) line[lp++] = (char)(d < 10 ? '0' + d : 'a' + d - 10);
  }
}
static void drain(void) { if (lp) { htif_write(line, lp); lp = 0; } }
static void flush(void) { line[lp++] = '\n'; if (lp >= MB_CHUNK) drain(); }

static u64 checksum(const u64 *o, u32 n) {
  u64 h = 0xcbf29ce484222325ULL;
  for (u32 i = 0; i < n; i++) { h ^= o[i]; h *= 0x100000001b3ULL; }
  return h;
}

static inline u64 rdcycle(void) { u64 v; asm volatile("rdcycle %0" : "=r"(v)); return v; }

static u64 outbuf[64];

int main(void) {
  u64 t0 = rdcycle();
  unsigned pass = 0, fail = 0;
  u64 marchid, mimpid, misa;
  asm volatile("csrr %0, marchid" : "=r"(marchid));
  asm volatile("csrr %0, mimpid" : "=r"(mimpid));
  asm volatile("csrr %0, misa" : "=r"(misa));
  /* marchid: 1 = Rocket, 2 = BOOM, 5 = spike (RISC-V arch-id registry) */
  ps("MB-BEGIN group="); ps(GROUP); ps(" n="); pu(NKERNELS); ps(" reps="); pu(MB_REPS); ps(" warm=1");
  ps(" marchid="); pu(marchid); ps(" mimpid="); px(mimpid); ps(" misa="); px(misa); flush();
  drain();
  for (unsigned k = 0; k < NKERNELS; k++) {
    const kern_t *K = &KERNELS[k];
    u64 t[2], cyc[MB_REPS], ins[MB_REPS], sum = 0;
    int ok = 1;
    K->fn(K->in, outbuf, t); /* warmup: I$/D$/predictor */
    if (checksum(outbuf, K->nout) != K->expect) ok = 0;
    for (int r = 0; r < MB_REPS; r++) {
      K->fn(K->in, outbuf, t);
      cyc[r] = t[0];
      ins[r] = t[1];
      sum = checksum(outbuf, K->nout);
      if (sum != K->expect) ok = 0;
    }
    if (ok) pass++; else fail++;
    ps("MB k="); ps(K->name); ps(" ops="); pu(K->ops); ps(" cyc=");
    for (int r = 0; r < MB_REPS; r++) { if (r) ps(","); pu(cyc[r]); }
    ps(" ins=");
    for (int r = 0; r < MB_REPS; r++) { if (r) ps(","); pu(ins[r]); }
    ps(" sum="); px(sum); ps(" exp="); px(K->expect); ps(" ok="); pu(ok); flush();
  }
  ps("MB-END group="); ps(GROUP); ps(" pass="); pu(pass); ps(" fail="); pu(fail);
  ps(" total_cycles="); pu(rdcycle() - t0); flush();
  drain();
  return fail ? 2 : 0;
}
