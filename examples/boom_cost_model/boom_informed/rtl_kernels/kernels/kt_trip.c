/* Trip-count study: a loop of T iterations dividing by a divisor that is
   invariant in the loop but changes per call (so any reciprocal setup is paid
   once per call).  Each entry runs TC_R calls at one T. */
#include "rk.h"

static u64 __attribute__((noipa)) F(tdiv64)(const u64 *a, int T, u64 d) {
  u64 s = 0;
  for (int i = 0; i < T; i++) s += a[i] / d;
  return s;
}
static u64 __attribute__((noipa)) F(tdiv32)(const u64 *a, int T, u32 d) {
  u64 s = 0;
  for (int i = 0; i < T; i++) s += (u32)a[i] / d;
  return s;
}

#define TC_ENTRY(nm, fn, arr, dexpr, T)                                \
  u64 F(nm##_T##T)(u64 *tm) {                                          \
    u64 h = 0;                                                         \
    TSTART(tm);                                                        \
    for (int r = 0; r < TC_R; r++) h += fn(arr + r * TC_MAXT, T, dexpr); \
    TSTOP(tm);                                                         \
    return h;                                                          \
  }
#define TC_ALL(nm, fn, arr, dexpr) \
  TC_ENTRY(nm, fn, arr, dexpr, 1) TC_ENTRY(nm, fn, arr, dexpr, 2) TC_ENTRY(nm, fn, arr, dexpr, 4) \
  TC_ENTRY(nm, fn, arr, dexpr, 8) TC_ENTRY(nm, fn, arr, dexpr, 32)

/* u64 ptr-diff / es=8 (qsort-like, small dividends) */
TC_ALL(tc_u64es, F(tdiv64), tc_small, (u64)qs_es)
/* u64 large dividends, 20-bit divisors */
TC_ALL(tc_u64big, F(tdiv64), tc_big, tc_div_big[r])
/* u32 dividends, divisors 3..2002 */
TC_ALL(tc_u32, F(tdiv32), tc_big, tc_div32[r])
