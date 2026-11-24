/* Kernels for the FPGA probe; compiled twice (PFX=base_ without plugin,
   PFX=inv_ with boom_invariant_div defaults). */
#ifndef PFX
#define PFX base_
#endif
#define CAT2(a,b) a##b
#define CAT(a,b) CAT2(a,b)
#define F(name) CAT(PFX,name)
#define NI __attribute__((noinline,noipa))
typedef unsigned long long u64; typedef long long s64; typedef unsigned int u32; typedef int s32; typedef unsigned long size_t;
NI u64 F(u32_div)(const u32 *a, size_t n, u32 d){ u64 s=0; for(size_t i=0;i<n;i++) s+=a[i]/d; return s; }
NI u64 F(u32_mod)(const u32 *a, size_t n, u32 d){ u64 s=0; for(size_t i=0;i<n;i++) s+=a[i]%d; return s; }
NI u64 F(u32_divmod)(const u32 *a, size_t n, u32 d){ u64 s=0; for(size_t i=0;i<n;i++) s+=(a[i]/d)*3 + a[i]%d; return s; }
NI s64 F(s32_div)(const s32 *a, size_t n, s32 d){ s64 s=0; for(size_t i=0;i<n;i++) s+=a[i]/d; return s; }
NI u64 F(u64_div)(const u64 *a, size_t n, u64 d){ u64 s=0; for(size_t i=0;i<n;i++) s+=a[i]/d; return s; }
NI u64 F(u64_mod)(const u64 *a, size_t n, u64 d){ u64 s=0; for(size_t i=0;i<n;i++) s+=a[i]%d; return s; }
/* dependent chain: each division depends on the previous result (latency-bound) */
NI u32 F(u32_chain)(u32 x, size_t n, u32 d){ for(size_t i=0;i<n;i++) x = x/d + (x ^ (u32)i) * 2654435761u; return x; }
