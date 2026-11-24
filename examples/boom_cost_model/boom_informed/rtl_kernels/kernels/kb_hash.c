/* (b) transposition-table-like probes: slot = (u32)hash % tt_size, tt_size a
   global set once at init; pointer-chasing loads between probes.
   kb_ro: read-only probes into a u64 table.
   kb_rw: probe + replace into a table with u32 fields; the u32 stores may
          alias the u32 global tt_size, so its load cannot be hoisted. */
#include "rk.h"

u64 F(kb_ro)(u64 *tm) {
  u32 idx = 0;
  u64 key = 0x123456789abcdefULL, acc = 0;
  TSTART(tm);
  for (int i = 0; i < NPROBE; i++) {
    idx = chain[idx];                       /* dependent load */
    key = (key ^ idx) * 0x9E3779B97F4A7C15ULL;
    u32 slot = (u32)(key >> 29) % tt_size;
    u64 e = tt64[slot];
    if ((e >> 48) == (key >> 48)) acc += 1000;
    acc += e & 0xff;
  }
  TSTOP(tm);
  return rk_mix(acc, key);
}

u64 F(kb_rw)(u64 *tm) {
  u32 idx = 0;
  u64 key = 0xfedcba9876543210ULL, acc = 0;
  { tte_t *d = tt32; const tte_t *o = tt32_orig;
    for (u32 k = 0; k < TT_ENT; k++) d[k] = o[k]; }
  TSTART(tm);
  for (int i = 0; i < NPROBE; i++) {
    idx = chain[idx];
    key = (key ^ idx) * 0x9E3779B97F4A7C15ULL;
    u32 slot = (u32)(key >> 29) % tt_size;
    tte_t *e = &tt32[slot];
    u32 tag = (u32)(key >> 40);
    if (e->tag == tag) {
      acc += e->data;
    } else if ((e->data & 3) != 0) { /* replace */
      e->tag = tag;
      e->data = (u32)key | 1u;
    }
  }
  TSTOP(tm);
  return rk_mix(acc, key);
}
