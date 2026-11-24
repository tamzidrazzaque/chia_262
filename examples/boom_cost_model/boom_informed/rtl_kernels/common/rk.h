/* rtl-kernels common header.  Kernels are written from scratch; they mimic
   only the computational pattern of the SPEC sites (no SPEC code). */
#ifndef RK_H
#define RK_H
#include <stdint.h>
#include <stddef.h>
typedef uint64_t u64;
typedef int64_t s64;
typedef uint32_t u32;
typedef int32_t s32;

#define RK_CAT2(a, b) a##b
#define RK_CAT(a, b) RK_CAT2(a, b)
#ifndef PFX
#define PFX x_
#endif
#define F(n) RK_CAT(PFX, n)

#ifdef __riscv
static inline u64 rk_cyc(void) { u64 v; __asm__ volatile("rdcycle %0" : "=r"(v)::"memory"); return v; }
static inline u64 rk_ins(void) { u64 v; __asm__ volatile("rdinstret %0" : "=r"(v)::"memory"); return v; }
#else
static inline u64 rk_cyc(void) { return 0; }
static inline u64 rk_ins(void) { return 0; }
#endif
/* tm[0]=cycles tm[1]=instret of the timed region */
#define TSTART(tm) do { (tm)[0] = rk_cyc(); (tm)[1] = rk_ins(); } while (0)
#define TSTOP(tm)  do { u64 i_ = rk_ins(); u64 c_ = rk_cyc(); (tm)[1] = i_ - (tm)[1]; (tm)[0] = c_ - (tm)[0]; } while (0)

static inline u64 rk_mix(u64 h, u64 v) { h ^= v; h *= 0x100000001b3ULL; return h; }

/* ---- shared input data, built by rk_data.c (stock flags) ---- */
#define QS_N 400
extern u64 qs_src[QS_N];          /* (a) keys to sort */
extern volatile u64 qs_es;        /* (a) element size, runtime = 8 */

#define TT_ENT 12289u             /* (b) table capacity */
#define CH_N 4096
#define NPROBE 1536
extern u32 tt_size;               /* (b) set once at init, never changes */
extern u64 *tt64;                 /* (b) table, read-only probe variant */
typedef struct { u32 tag; u32 data; } tte_t;
extern tte_t *tt32;               /* (b) table with u32 fields (stores may alias tt_size) */
extern const tte_t *tt32_orig;    /* (b) pristine copy, restored before each kb_rw call */
extern u32 chain[CH_N];           /* (b) pointer-chase links */

#define UCT_KIDS 32
#define UCT_ROUNDS 24
typedef struct { s32 visits; s32 wins; float prior; s32 pad; } kid_t;
extern kid_t uct_init[UCT_KIDS];

#define KD_N 255
#define KD_DIM_MAX 4
#define KD_Q 24
extern float kd_pts[KD_N * KD_DIM_MAX];
extern float kd_q[KD_Q * KD_DIM_MAX];
extern volatile s32 kd_dim;       /* runtime = 3 */

#define MC_N 512
extern unsigned char mc_bytes[MC_N];
extern s64 mc_big[MC_N];

#define TC_R 16
#define TC_MAXT 32
extern u64 tc_small[TC_R * TC_MAXT];
extern u64 tc_big[TC_R * TC_MAXT];
extern u64 tc_div_big[TC_R];
extern u32 tc_div32[TC_R];

void rk_data_init(void);
#endif
