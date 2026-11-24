/* Correctness driver: compares plugin-compiled kernels (opt_*) against the
   same source compiled at -O0 without the plugin (ref_*).  Run under QEMU. */
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DECL(P) \
void P##u32_div(uint32_t*,const uint32_t*,size_t,uint32_t); \
void P##u32_mod(uint32_t*,const uint32_t*,size_t,uint32_t); \
void P##s32_div(int32_t*,const int32_t*,size_t,int32_t); \
void P##s32_mod(int32_t*,const int32_t*,size_t,int32_t); \
void P##u64_div(uint64_t*,const uint64_t*,size_t,uint64_t); \
void P##u64_mod(uint64_t*,const uint64_t*,size_t,uint64_t); \
void P##s64_div(int64_t*,const int64_t*,size_t,int64_t); \
void P##s64_mod(int64_t*,const int64_t*,size_t,int64_t); \
void P##u32_divmod(uint32_t*,uint32_t*,const uint32_t*,size_t,uint32_t); \
void P##s32_divmod(int32_t*,int32_t*,const int32_t*,size_t,int32_t); \
void P##u64_divmod(uint64_t*,uint64_t*,const uint64_t*,size_t,uint64_t); \
void P##s64_divmod(int64_t*,int64_t*,const int64_t*,size_t,int64_t); \
uint32_t P##u32_multi(const uint32_t*,const uint32_t*,size_t,uint32_t,uint32_t); \
uint32_t P##u32_zerotrip(const uint32_t*,size_t,uint32_t); \
int64_t P##s32_early(const int32_t*,size_t,int32_t,int32_t); \
uint64_t P##u32_nested(const uint32_t*,size_t,size_t,uint32_t); \
uint64_t P##u32_outerdef(const uint32_t*,const uint32_t*,size_t,size_t); \
int64_t P##s64_outerdef(const int64_t*,const int64_t*,size_t,size_t); \
uint32_t P##u32_cond(const uint32_t*,size_t,uint32_t); \
uint64_t P##u32_iv(uint32_t,uint32_t,uint32_t); \
uint32_t P##u16_promoted(const uint16_t*,size_t,uint16_t); \
uint32_t P##u32_trip2(const uint32_t*,uint32_t); \
uint32_t P##u32_trip1000(const uint32_t*,uint32_t); \
uint32_t P##u32_variant(const uint32_t*,size_t,uint32_t); \
uint32_t P##u32_bounded3(const uint32_t*,size_t,uint32_t); \
void P##u8_div(uint8_t*,const uint8_t*,size_t,uint8_t); \
void P##s16_mod(int16_t*,const int16_t*,size_t,int16_t);
DECL(opt_)
DECL(ref_)

static uint64_t st = 0x9E3779B97F4A7C15ull;
static uint64_t rnd(void){ uint64_t z=(st+=0x9E3779B97F4A7C15ull); z=(z^(z>>30))*0xBF58476D1CE4E5B9ull; z=(z^(z>>27))*0x94D049BB133111EBull; return z^(z>>31); }
/* random value with random bit length (so small values are common) */
static uint64_t rbits(int maxbits){ int b = (int)(rnd()%(unsigned)(maxbits+1)); if(b==0) return 0; uint64_t v=rnd(); if(b<64) v &= (1ull<<b)-1; v |= 1ull<<(b-1); return v; }

static unsigned long long checked, bad;
#define REPORT(fmt, ...) do{ if(bad<20) printf("MISMATCH " fmt "\n", __VA_ARGS__); bad++; }while(0)

#define M 128
static uint32_t a32[M], o1[M], o2[M], o3[M], o4[M];
static uint64_t a64[M], p1[M], p2[M], p3[M], p4[M];

/* fill dividends for divisor magnitude dm (edges + random) */
static size_t fill32(uint64_t dm, int sgn){
  size_t k=0; uint32_t e[] = {0,1,2,3,(uint32_t)dm-1,(uint32_t)dm,(uint32_t)dm+1,(uint32_t)(2*dm-1),(uint32_t)(2*dm),(uint32_t)(2*dm+1),
     0xFFFFFFFFu,0xFFFFFFFEu,0x80000000u,0x7FFFFFFFu,0x80000001u,0x7FFFFFFEu};
  for(size_t i=0;i<sizeof e/sizeof e[0];i++) a32[k++]=e[i];
  for(int j=0;j<16;j++){ uint64_t m=(rnd()%(0x100000000ull/(dm?dm:1)+1))*dm; a32[k++]=(uint32_t)m; a32[k++]=(uint32_t)(m-1); }
  while(k<M) a32[k++]=(uint32_t)rbits(32);
  if(sgn) for(size_t i=0;i<M;i++) if(rnd()&1) a32[i]=(uint32_t)(-(int32_t)a32[i]);
  return M;
}
static size_t fill64(uint64_t dm, int sgn){
  size_t k=0; uint64_t e[] = {0,1,2,3,dm-1,dm,dm+1,2*dm-1,2*dm,2*dm+1,~0ull,~0ull-1,1ull<<63,(1ull<<63)-1,(1ull<<63)+1,0xFFFFFFFFull,0x100000000ull};
  for(size_t i=0;i<sizeof e/sizeof e[0];i++) a64[k++]=e[i];
  for(int j=0;j<16;j++){ uint64_t lim = ~0ull/(dm?dm:1); uint64_t m=(lim? rnd()%lim : 0)*dm; a64[k++]=m; a64[k++]=m-1; a64[k++]=m+dm-1; }
  while(k<M) a64[k++]=rbits(64);
  if(sgn) for(size_t i=0;i<M;i++) if(rnd()&1) a64[i]=(uint64_t)(-(int64_t)a64[i]);
  return M;
}
/* avoid INT_MIN / -1 (UB) */
static void fix_s32(int32_t d){ if(d==-1) for(size_t i=0;i<M;i++) if(a32[i]==0x80000000u) a32[i]=0x80000001u; }
static void fix_s64(int64_t d){ if(d==-1) for(size_t i=0;i<M;i++) if(a64[i]==(1ull<<63)) a64[i]=(1ull<<63)+1; }

static void cmp32(const char *k, uint64_t d, size_t n){ for(size_t i=0;i<n;i++){ checked++; if(o1[i]!=o2[i]) REPORT("%s d=%#llx n=%#x opt=%#x ref=%#x",k,(unsigned long long)d,a32[i],o1[i],o2[i]); } }
static void cmp64(const char *k, uint64_t d, size_t n){ for(size_t i=0;i<n;i++){ checked++; if(p1[i]!=p2[i]) REPORT("%s d=%#llx n=%#llx opt=%#llx ref=%#llx",k,(unsigned long long)d,(unsigned long long)a64[i],(unsigned long long)p1[i],(unsigned long long)p2[i]); } }

static void t_u32(uint32_t d, size_t n){
  opt_u32_div(o1,a32,n,d); ref_u32_div(o2,a32,n,d); cmp32("u32_div",d,n);
  opt_u32_mod(o1,a32,n,d); ref_u32_mod(o2,a32,n,d); cmp32("u32_mod",d,n);
  opt_u32_divmod(o1,o3,a32,n,d); ref_u32_divmod(o2,o4,a32,n,d); cmp32("u32_divmod.q",d,n); memcpy(o1,o3,sizeof o1); memcpy(o2,o4,sizeof o2); cmp32("u32_divmod.r",d,n);
}
static void t_s32(int32_t d, size_t n){
  fix_s32(d);
  opt_s32_div((int32_t*)o1,(int32_t*)a32,n,d); ref_s32_div((int32_t*)o2,(int32_t*)a32,n,d); cmp32("s32_div",(uint32_t)d,n);
  opt_s32_mod((int32_t*)o1,(int32_t*)a32,n,d); ref_s32_mod((int32_t*)o2,(int32_t*)a32,n,d); cmp32("s32_mod",(uint32_t)d,n);
  opt_s32_divmod((int32_t*)o1,(int32_t*)o3,(int32_t*)a32,n,d); ref_s32_divmod((int32_t*)o2,(int32_t*)o4,(int32_t*)a32,n,d); cmp32("s32_divmod.q",(uint32_t)d,n); memcpy(o1,o3,sizeof o1); memcpy(o2,o4,sizeof o2); cmp32("s32_divmod.r",(uint32_t)d,n);
}
static void t_u64(uint64_t d, size_t n){
  opt_u64_div(p1,a64,n,d); ref_u64_div(p2,a64,n,d); cmp64("u64_div",d,n);
  opt_u64_mod(p1,a64,n,d); ref_u64_mod(p2,a64,n,d); cmp64("u64_mod",d,n);
  opt_u64_divmod(p1,p3,a64,n,d); ref_u64_divmod(p2,p4,a64,n,d); cmp64("u64_divmod.q",d,n); memcpy(p1,p3,sizeof p1); memcpy(p2,p4,sizeof p2); cmp64("u64_divmod.r",d,n);
}
static void t_s64(int64_t d, size_t n){
  fix_s64(d);
  opt_s64_div((int64_t*)p1,(int64_t*)a64,n,d); ref_s64_div((int64_t*)p2,(int64_t*)a64,n,d); cmp64("s64_div",(uint64_t)d,n);
  opt_s64_mod((int64_t*)p1,(int64_t*)a64,n,d); ref_s64_mod((int64_t*)p2,(int64_t*)a64,n,d); cmp64("s64_mod",(uint64_t)d,n);
  opt_s64_divmod((int64_t*)p1,(int64_t*)p3,(int64_t*)a64,n,d); ref_s64_divmod((int64_t*)p2,(int64_t*)p4,(int64_t*)a64,n,d); cmp64("s64_divmod.q",(uint64_t)d,n); memcpy(p1,p3,sizeof p1); memcpy(p2,p4,sizeof p2); cmp64("s64_divmod.r",(uint64_t)d,n);
}

static void edge32(void){
  /* all powers of two, 2^k +- 1, 2^31, 2^32-1 and neighbours */
  for(int k=0;k<32;k++){ uint64_t p=1ull<<k; uint64_t c[]={p,p-1,p+1,p-2,p+2};
    for(int j=0;j<5;j++){ uint32_t d=(uint32_t)c[j]; if(!d) continue; fill32(d,0); t_u32(d,M); fill32(d,1); t_s32((int32_t)d,M); t_s32(-(int32_t)d,M); } }
  uint32_t ex[]={0x80000000u,0xFFFFFFFFu,0xFFFFFFFEu,0x7FFFFFFFu,0x80000001u,0xFFFF0001u,0x10001u,0xAAAAAAABu,0x55555555u,3,5,7,641,6700417};
  for(size_t i=0;i<sizeof ex/sizeof ex[0];i++){ fill32(ex[i],0); t_u32(ex[i],M); fill32(ex[i],1); t_s32((int32_t)ex[i],M); if(ex[i]!=0x80000000u) t_s32(-(int32_t)ex[i],M); }
}
static void edge64(void){
  for(int k=0;k<64;k++){ uint64_t p=1ull<<k; uint64_t c[]={p,p-1,p+1,p-2,p+2};
    for(int j=0;j<5;j++){ uint64_t d=c[j]; if(!d) continue; fill64(d,0); t_u64(d,M); fill64(d,1); t_s64((int64_t)d,M); if(d!=(1ull<<63)) t_s64(-(int64_t)d,M); } }
  uint64_t ex[]={~0ull,~0ull-1,(1ull<<63),(1ull<<63)+1,(1ull<<63)-1,0xFFFFFFFFull,0x100000001ull,0xAAAAAAAAAAAAAAABull,0x5555555555555555ull,3,7,274177,67280421310721ull,0xFFFFFFFF00000001ull};
  for(size_t i=0;i<sizeof ex/sizeof ex[0];i++){ fill64(ex[i],0); t_u64(ex[i],M); fill64(ex[i],1); t_s64((int64_t)ex[i],M); if(ex[i]!=(1ull<<63)) t_s64(-(int64_t)ex[i],M); }
  /* random divisors of every bit length */
  for(int b=1;b<=64;b++) for(int j=0;j<200;j++){ uint64_t d=rbits(64); int bb=b; d = (bb==64? rnd() : (rnd() & ((1ull<<bb)-1))) | (1ull<<(bb-1));
    fill64(d,0); t_u64(d,M); fill64(d,1); t_s64((int64_t)d,M); if(d!=(1ull<<63)) t_s64(-(int64_t)d,M); }
}
static void exh(uint32_t lo, uint32_t hi){
  for(uint32_t d=lo; d<=hi; d++){
    fill32(d,0); t_u32(d,M);
    fill32(d,1); t_s32((int32_t)d,M); t_s32(-(int32_t)d,M);
    fill64(d,0); t_u64(d,M);
    fill64(d,1); t_s64((int64_t)d,M); t_s64(-(int64_t)d,M);
  }
}
static void rand_pairs(unsigned long long target){
  unsigned long long start=checked;
  while(checked-start < target){
    size_t n = 1 + rnd()%32;
    uint32_t d32 = (uint32_t)rbits(32); if(!d32) d32=1;
    for(size_t i=0;i<n;i++) a32[i]=(uint32_t)rbits(32);
    t_u32(d32,n);
    int32_t s32 = (int32_t)d32; if(rnd()&1) s32 = (int32_t)(0u - d32); if(!s32) s32=1;
    for(size_t i=0;i<n;i++) if(rnd()&1) a32[i]=(uint32_t)(-(int32_t)a32[i]);
    t_s32(s32,n);
    uint64_t d64 = rbits(64); if(!d64) d64=1;
    for(size_t i=0;i<n;i++) a64[i]=rbits(64);
    t_u64(d64,n);
    for(size_t i=0;i<n;i++) if(rnd()&1) a64[i]=(uint64_t)(-(int64_t)a64[i]);
    t_s64(rnd()&1 ? (int64_t)d64 : -(int64_t)d64, n);
  }
}

static uint32_t big32[1<<16]; static int32_t bigs32[1<<16]; static int64_t bigs64[1<<14]; static uint16_t big16[4096];
#define CHK(name, x, y) do{ checked++; if((x)!=(y)) REPORT("%s iter=%d opt=%#llx ref=%#llx", name, it, (unsigned long long)(x), (unsigned long long)(y)); }while(0)
static void shapes(int iters){
  for(size_t i=0;i<(1<<16);i++){ big32[i]=(uint32_t)rbits(32); bigs32[i]=(int32_t)rbits(32)*((rnd()&1)?1:-1); }
  for(size_t i=0;i<(1<<14);i++) bigs64[i]=(int64_t)rbits(63)*((rnd()&1)?1:-1);
  for(size_t i=0;i<4096;i++) big16[i]=(uint16_t)rnd();
  for(int it=0; it<iters; it++){
    uint32_t d = (uint32_t)rbits(32); if(!d) d=1; if(it%7==0) d=1; if(it%11==0) d=0xFFFFFFFFu;
    uint32_t e = (uint32_t)rbits(20)+1;
    size_t n = rnd()%3000; if(it%5==0) n=0;
    CHK("u32_multi", opt_u32_multi(big32,big32+3000,n,d,e), ref_u32_multi(big32,big32+3000,n,d,e));
    /* zero-trip with d == 0 must be harmless */
    CHK("u32_zerotrip_d0", opt_u32_zerotrip(big32,0,0), ref_u32_zerotrip(big32,0,0));
    CHK("u32_zerotrip", opt_u32_zerotrip(big32,n,d), ref_u32_zerotrip(big32,n,d));
    int32_t sd = (int32_t)rbits(31)+1; if(rnd()&1) sd=-sd; if(it%13==0) sd=-1; if(it%17==0) sd=1;
    int32_t stop = (int32_t)(rnd()%64) - 32;
    /* avoid INT_MIN/-1: bigs32 holds values with |v| < 2^31 by construction except rbits(32)*-1 overflow */
    if(sd==-1) for(size_t i=0;i<n;i++) if(bigs32[i]==INT32_MIN) bigs32[i]=0;
    CHK("s32_early", opt_s32_early(bigs32,n,sd,stop), ref_s32_early(bigs32,n,sd,stop));
    size_t rows = rnd()%40, cols = rnd()%60;
    CHK("u32_nested", opt_u32_nested(big32,rows,cols,d), ref_u32_nested(big32,rows,cols,d));
    uint32_t dsv[64]; for(int j=0;j<64;j++){ dsv[j]=(uint32_t)rbits(32); if(!dsv[j]) dsv[j]=1; }
    CHK("u32_outerdef", opt_u32_outerdef(big32,dsv,rows,cols), ref_u32_outerdef(big32,dsv,rows,cols));
    int64_t dsv64[64]; for(int j=0;j<64;j++){ dsv64[j]=(int64_t)rbits(63); if(!dsv64[j]) dsv64[j]=1; if(rnd()&1) dsv64[j]=-dsv64[j]; }
    CHK("s64_outerdef", opt_s64_outerdef(bigs64,dsv64,rows,cols), ref_s64_outerdef(bigs64,dsv64,rows,cols));
    CHK("u32_cond", opt_u32_cond(big32,n,d), ref_u32_cond(big32,n,d));
    uint32_t lo = (uint32_t)rnd(), span=(uint32_t)(rnd()%2000); uint32_t hi = lo+span < lo ? 0xFFFFFFFFu : lo+span;
    CHK("u32_iv", opt_u32_iv(lo,hi,d), ref_u32_iv(lo,hi,d));
    CHK("u32_iv_small", opt_u32_iv(0,span,e), ref_u32_iv(0,span,e));
    uint16_t d16 = (uint16_t)rnd(); if(!d16) d16=1;
    CHK("u16_promoted", opt_u16_promoted(big16,n<4096?n:4096,d16), ref_u16_promoted(big16,n<4096?n:4096,d16));
    CHK("u32_trip2", opt_u32_trip2(big32,d), ref_u32_trip2(big32,d));
    CHK("u32_trip1000", opt_u32_trip1000(big32,d), ref_u32_trip1000(big32,d));
    CHK("u32_variant", opt_u32_variant(big32,n,d), ref_u32_variant(big32,n,d));
    CHK("u32_bounded3", opt_u32_bounded3(big32,n,d), ref_u32_bounded3(big32,n,d));
    { uint8_t x[256], y1[256], y2[256]; uint8_t d8=(uint8_t)(rnd()%255+1); for(int j=0;j<256;j++) x[j]=(uint8_t)j;
      opt_u8_div(y1,x,256,d8); ref_u8_div(y2,x,256,d8); for(int j=0;j<256;j++) CHK("u8_div", y1[j], y2[j]); }
    { int16_t x[512], y1[512], y2[512]; int16_t d16s=(int16_t)rnd(); if(!d16s) d16s=1; for(int j=0;j<512;j++) x[j]=(int16_t)rnd();
      x[0]=INT16_MIN; x[1]=INT16_MAX; x[2]=0; x[3]=-1;
      opt_s16_mod(y1,x,512,d16s); ref_s16_mod(y2,x,512,d16s); for(int j=0;j<512;j++) CHK("s16_mod", y1[j], y2[j]); }
  }
}

int main(int argc, char **argv){
  const char *ph = argc>1 ? argv[1] : "all";
  if(argc>4) st = strtoull(argv[4],0,0);
  if(!strcmp(ph,"edge")||!strcmp(ph,"all")){ edge32(); edge64(); }
  if(!strcmp(ph,"exh")){ uint32_t lo=(uint32_t)strtoul(argv[2],0,0), hi=(uint32_t)strtoul(argv[3],0,0); exh(lo,hi); }
  if(!strcmp(ph,"rand")){ rand_pairs(strtoull(argv[2],0,0)); }
  if(!strcmp(ph,"shapes")||!strcmp(ph,"all")){ shapes(argc>2?atoi(argv[2]):200); }
  printf("phase=%s checked=%llu mismatches=%llu\n", ph, checked, bad);
  return bad!=0;
}
