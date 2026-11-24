/* (e) modulo by the constant 1000003.
   ke_chain_s64: h = (h*31 + byte) % 1000003, signed 64-bit, loop-carried
                 (small dividends: < 2^25).
   ke_indep_s64: sum of x[i] % 1000003 for independent 62-bit x (signed 64).
   ke_chain_u32: as chain but unsigned 32-bit. */
#include "rk.h"

u64 F(ke_chain_s64)(u64 *tm) {
  s64 h = 7;
  TSTART(tm);
  for (int i = 0; i < MC_N; i++) h = (h * 31 + mc_bytes[i]) % 1000003;
  TSTOP(tm);
  return (u64)h;
}

u64 F(ke_indep_s64)(u64 *tm) {
  s64 s = 0;
  TSTART(tm);
  for (int i = 0; i < MC_N; i++) s += mc_big[i] % 1000003;
  TSTOP(tm);
  return (u64)s;
}

u64 F(ke_chain_u32)(u64 *tm) {
  u32 h = 7;
  TSTART(tm);
  for (int i = 0; i < MC_N; i++) h = (h * 31u + mc_bytes[i]) % 1000003u;
  TSTOP(tm);
  return (u64)h;
}

/* mcf-like constant 4000 (the occupancy plugin handles this multiplier;
   it does not handle 1000003, whose multiplier needs the add form). */
u64 F(ke_chain_s64_4000)(u64 *tm) {
  s64 h = 7;
  TSTART(tm);
  for (int i = 0; i < MC_N; i++) h = (h * 31 + mc_bytes[i]) % 4000;
  TSTOP(tm);
  return (u64)h;
}

u64 F(ke_indep_s64_4000)(u64 *tm) {
  s64 s = 0;
  TSTART(tm);
  for (int i = 0; i < MC_N; i++) s += mc_big[i] / 4000 + mc_big[i] % 4000;
  TSTOP(tm);
  return (u64)s;
}
