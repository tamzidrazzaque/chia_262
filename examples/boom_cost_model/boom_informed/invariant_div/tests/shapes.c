/* Loop-shape kernels.  Compiled twice: with the plugin (-O2/-O3) and as a
   reference at -O0 without plugin (PFX=ref_).  */
#include <stdint.h>
#include <stddef.h>
#ifndef PFX
#define PFX opt_
#endif
#define CAT2(a,b) a##b
#define CAT(a,b) CAT2(a,b)
#define F(name) CAT(PFX,name)
#define NI __attribute__((noinline,noipa))

/* straight kernels (all kinds, div and mod) */
NI void F(u32_div)(uint32_t *o, const uint32_t *a, size_t n, uint32_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]/d; }
NI void F(u32_mod)(uint32_t *o, const uint32_t *a, size_t n, uint32_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]%d; }
NI void F(s32_div)(int32_t *o, const int32_t *a, size_t n, int32_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]/d; }
NI void F(s32_mod)(int32_t *o, const int32_t *a, size_t n, int32_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]%d; }
NI void F(u64_div)(uint64_t *o, const uint64_t *a, size_t n, uint64_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]/d; }
NI void F(u64_mod)(uint64_t *o, const uint64_t *a, size_t n, uint64_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]%d; }
NI void F(s64_div)(int64_t *o, const int64_t *a, size_t n, int64_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]/d; }
NI void F(s64_mod)(int64_t *o, const int64_t *a, size_t n, int64_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]%d; }

/* div and mod together, same divisor (one shared setup) */
NI void F(u32_divmod)(uint32_t *q, uint32_t *r, const uint32_t *a, size_t n, uint32_t d){
  for(size_t i=0;i<n;i++){ q[i]=a[i]/d; r[i]=a[i]%d; } }
NI void F(s32_divmod)(int32_t *q, int32_t *r, const int32_t *a, size_t n, int32_t d){
  for(size_t i=0;i<n;i++){ q[i]=a[i]/d; r[i]=a[i]%d; } }
NI void F(u64_divmod)(uint64_t *q, uint64_t *r, const uint64_t *a, size_t n, uint64_t d){
  for(size_t i=0;i<n;i++){ q[i]=a[i]/d; r[i]=a[i]%d; } }
NI void F(s64_divmod)(int64_t *q, int64_t *r, const int64_t *a, size_t n, int64_t d){
  for(size_t i=0;i<n;i++){ q[i]=a[i]/d; r[i]=a[i]%d; } }

/* multiple divisions sharing a divisor, plus a second divisor */
NI uint32_t F(u32_multi)(const uint32_t *a, const uint32_t *b, size_t n, uint32_t d, uint32_t e){
  uint32_t s=0; for(size_t i=0;i<n;i++){ s += a[i]/d + b[i]/d + (a[i]^b[i])%d + a[i]/e + (b[i]+i)%e; } return s; }

/* zero-trip loop with d==0 allowed by caller (must not trap/misbehave) */
NI uint32_t F(u32_zerotrip)(const uint32_t *a, size_t n, uint32_t d){
  uint32_t s=0; for(size_t i=0;i<n;i++) s += a[i]/d; return s; }

/* early exit */
NI int64_t F(s32_early)(const int32_t *a, size_t n, int32_t d, int32_t stop){
  int64_t s=0; for(size_t i=0;i<n;i++){ int32_t q=a[i]/d; if(q==stop) return -(int64_t)i-1; s+=q + a[i]%d; } return s; }

/* nested: divisor invariant in both loops (setup should go to outer preheader) */
NI uint64_t F(u32_nested)(const uint32_t *a, size_t rows, size_t cols, uint32_t d){
  uint64_t s=0; for(size_t r=0;r<rows;r++) for(size_t c=0;c<cols;c++) s += a[r*cols+c]/d + (a[r*cols+c]%d)*3; return s; }

/* divisor defined in the outer loop (setup must be in the inner preheader) */
NI uint64_t F(u32_outerdef)(const uint32_t *a, const uint32_t *ds, size_t rows, size_t cols){
  uint64_t s=0; for(size_t r=0;r<rows;r++){ uint32_t d=ds[r]; for(size_t c=0;c<cols;c++) s += a[r*cols+c]%d; } return s; }
NI int64_t F(s64_outerdef)(const int64_t *a, const int64_t *ds, size_t rows, size_t cols){
  int64_t s=0; for(size_t r=0;r<rows;r++){ int64_t d=ds[r]; for(size_t c=0;c<cols;c++) s += a[r*cols+c]/d - a[r*cols+c]%d; } return s; }

/* conditional division inside the loop */
NI uint32_t F(u32_cond)(const uint32_t *a, size_t n, uint32_t d){
  uint32_t s=0; for(size_t i=0;i<n;i++){ if(a[i]&1) s += a[i]/d; else s ^= a[i]; } return s; }

/* induction variable as dividend; while loop */
NI uint64_t F(u32_iv)(uint32_t lo, uint32_t hi, uint32_t d){
  uint64_t s=0; uint32_t i=lo; while(i<hi){ s += (uint64_t)(i%d)*(i/d); i++; } return s; }

/* 16-bit operands promoted to int (signed 32 division, nonneg ranges) */
NI uint32_t F(u16_promoted)(const uint16_t *a, size_t n, uint16_t d){
  uint32_t s=0; for(size_t i=0;i<n;i++) s += (uint32_t)(a[i]/d) * 7u + a[i]%d; return s; }

/* small constant trip count: profitability should say keep */
NI uint32_t F(u32_trip2)(const uint32_t *a, uint32_t d){
  uint32_t s=0; for(int i=0;i<2;i++) s += a[i]/d; return s; }
/* large constant trip count: profitable */
NI uint32_t F(u32_trip1000)(const uint32_t *a, uint32_t d){
  uint32_t s=0; for(int i=0;i<1000;i++) s += a[i]/d; return s; }
/* divisor computed in the loop: not invariant, must not be touched */
NI uint32_t F(u32_variant)(const uint32_t *a, size_t n, uint32_t d){
  uint32_t s=0; for(size_t i=0;i<n;i++) s += a[i]/(d+(uint32_t)i); return s; }
/* bounded small trip count (max niter 2, at most 3 executions): near the break-even point */
NI uint32_t F(u32_bounded3)(const uint32_t *a, size_t n, uint32_t d){
  uint32_t s=0; if(n>3) n=3; for(size_t i=0;i<n;i++) s += a[i]/d; return s; }
/* 8-bit and 16-bit explicit unsigned types without promotion games */
NI void F(u8_div)(uint8_t *o, const uint8_t *a, size_t n, uint8_t d){ for(size_t i=0;i<n;i++) o[i]=(uint8_t)(a[i]/d); }
NI void F(s16_mod)(int16_t *o, const int16_t *a, size_t n, int16_t d){ for(size_t i=0;i<n;i++) o[i]=(int16_t)(a[i]%d); }
