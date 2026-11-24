/* Host (x86) mirror of the exact formulas the pass emits, checked against
   native division for EVERY 32-bit dividend for a list of divisors
   (u32 and s32), and for structured+random 64-bit dividends (u64/s64).
   This validates the math independently of GCC/QEMU. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef unsigned __int128 u128;
static uint64_t mulhu(uint64_t a, uint64_t b){ return (uint64_t)(((u128)a*b)>>64); }
typedef struct { uint64_t ds, c, m1; unsigned sh1, sh2; } setup;
static setup su32(uint64_t du){ setup s; s.ds = du + (du==0); s.c = ~0ull/s.ds + 1; s.m1 = -(uint64_t)(s.ds==1); return s; }
static int use_inc;
/* inc: q = mulhu(c', n+1), c' = c - 1 = floor((2^64-1)/d);  mask: Lemire + d==1 mask */
static uint64_t q32(setup s, uint64_t n){ return use_inc ? mulhu(s.c-1, n+1) : mulhu(s.c,n) + (n & s.m1); }
static uint64_t r32(setup s, uint64_t n){ return mulhu(s.c*n, s.ds); }
static setup su64(uint64_t du){ setup s; s.ds = du + (du==0); uint64_t x=s.ds-1; uint64_t xs = x | (x==0);
  unsigned lm1 = 63 - __builtin_clzll(xs); uint64_t h = ((1ull<<lm1)<<1) - s.ds;
  s.c = (uint64_t)(((u128)h<<64)/s.ds) + 1; s.sh1 = s.ds!=1; s.sh2 = lm1; return s; }
static uint64_t q64(setup s, uint64_t n){ uint64_t t=mulhu(s.c,n); return (t + ((n-t)>>s.sh1))>>s.sh2; }
static uint64_t smask(int64_t v){ return (uint64_t)(v>>63); }
static uint64_t uabs(int64_t v){ uint64_t m=smask(v); return ((uint64_t)v^m)-m; }
static uint64_t rnd(void){ static uint64_t z0=88172645463325252ull; uint64_t z=(z0+=0x9E3779B97F4A7C15ull); z=(z^(z>>30))*0xBF58476D1CE4E5B9ull; z=(z^(z>>27))*0x94D049BB133111EBull; return z^(z>>31); }
int main(int argc, char **argv){
  int mode = atoi(argv[1]); use_inc = getenv("MASK") == NULL;  /* 0: u32 all n, 1: s32 all n, 2: u64/s64 sampled */
  unsigned long long bad=0, chk=0;
  for(int i=2;i<argc;i++){
    uint64_t dv = strtoull(argv[i],0,0);
    if(mode==0){ uint32_t d=(uint32_t)dv; setup s=su32(d);
      for(uint64_t n=0;n<=0xFFFFFFFFull;n++){ chk+=2; if((uint32_t)q32(s,n)!=(uint32_t)n/d) bad++; if((uint32_t)r32(s,n)!=(uint32_t)n%d) bad++; } }
    else if(mode==1){ int32_t d=(int32_t)(uint32_t)dv; uint64_t sd=smask(d); setup s=su32(uabs(d));
      for(int64_t n=INT32_MIN;n<=INT32_MAX;n++){ if(d==-1 && n==INT32_MIN) continue; chk+=2;
        uint64_t sn=smask(n), an=uabs(n); uint64_t uq=q32(s,an), ur=r32(s,an); uint64_t sq=sn^sd;
        int32_t q=(int32_t)((uq^sq)-sq), r=(int32_t)((ur^sn)-sn);
        if(q!=(int32_t)n/d) bad++; if(r!=(int32_t)n%d) bad++; } }
    else { uint64_t d=dv; setup s=su64(d); int64_t sdv=(int64_t)d; setup ss=su64(uabs(sdv)); uint64_t sd=smask(sdv);
      for(long k=0;k<(1L<<26);k++){ uint64_t n = (k<200)? (uint64_t)k : (k&1)? rnd() : rnd()>>(rnd()&63);
        if(k%3==0 && d>1){ uint64_t m=(rnd()%(~0ull/d))*d; n = (k&4)? m : m-1; }
        chk+=2; uint64_t q=q64(s,n); if(q!=n/d) bad++; if(n-q*s.ds != n%d) bad++;
        int64_t sn=(int64_t)n; if(sdv==-1 && sn==INT64_MIN) continue;
        uint64_t m=smask(sn), an=uabs(sn), uq=q64(ss,an), ur=an-uq*ss.ds, sq=m^sd; chk+=2;
        if((int64_t)((uq^sq)-sq)!=sn/sdv) bad++; if((int64_t)((ur^m)-m)!=sn%sdv) bad++; } }
  }
  printf("method=%s mode=%d checked=%llu mismatches=%llu\n", use_inc?"inc":"mask", mode, chk, bad); return bad!=0;
}
