/* Freestanding HTIF probe (same harness style as campaign/div_probe.c):
   cycles of base (GCC 15.1 -O2, runtime div/rem) vs inv (boom_invariant_div)
   for the same kernels, over trip counts and divisors.  Self-checks results. */
typedef unsigned long long u64; typedef long long s64; typedef unsigned int u32; typedef int s32; typedef unsigned long size_t;
volatile u64 tohost __attribute__((section(".tohost")));
volatile u64 fromhost __attribute__((section(".fromhost")));
static u64 htif_syscall(u64 which, u64 a0, u64 a1, u64 a2){ volatile u64 buf[8] __attribute__((aligned(64)));
  buf[0]=which; buf[1]=a0; buf[2]=a1; buf[3]=a2; fromhost=0; tohost=(u64)buf; while(fromhost==0){} fromhost=0; return buf[0]; }
static void put_s(const char *s){ u64 n=0; while(s[n]) n++; htif_syscall(64,1,(u64)s,n); }
static void put_u(u64 v){ char t[24]; int i=0; char o[24]; int j=0; if(!v){put_s("0");return;} while(v){ t[i++]='0'+(char)(v%10); v/=10; } while(i) o[j++]=t[--i]; o[j]=0; put_s(o); }
static inline u64 rdcycle(void){ u64 v; asm volatile("rdcycle %0":"=r"(v)); return v; }
static inline u64 rdinstret(void){ u64 v; asm volatile("rdinstret %0":"=r"(v)); return v; }
#define DECL(P) u64 P##u32_div(const u32*,size_t,u32); u64 P##u32_mod(const u32*,size_t,u32); u64 P##u32_divmod(const u32*,size_t,u32); \
 s64 P##s32_div(const s32*,size_t,s32); u64 P##u64_div(const u64*,size_t,u64); u64 P##u64_mod(const u64*,size_t,u64); u32 P##u32_chain(u32,size_t,u32);
DECL(base_) DECL(inv_)
#define NMAX 4096
static u32 A32[NMAX]; static u64 A64[NMAX];
static u64 st=0x1234567ULL; static u64 rnd(void){ u64 z=(st+=0x9E3779B97F4A7C15ULL); z=(z^(z>>30))*0xBF58476D1CE4E5B9ULL; z=(z^(z>>27))*0x94D049BB133111EBULL; return z^(z>>31); }
static u64 bad;
#define BENCH(name, call_b, call_i, n, d) do{ \
  u64 rb=call_b, ri=call_i; /* warm */ \
  u64 c0=rdcycle(), i0=rdinstret(); rb=call_b; u64 c1=rdcycle(), i1=rdinstret(); \
  u64 c2=rdcycle(), i2=rdinstret(); ri=call_i; u64 c3=rdcycle(), i3=rdinstret(); \
  put_s(name); put_s(" n="); put_u(n); put_s(" d="); put_u((u64)(d)); \
  put_s(" base_cyc="); put_u(c1-c0); put_s(" inv_cyc="); put_u(c3-c2); \
  put_s(" base_inst="); put_u(i1-i0); put_s(" inv_inst="); put_u(i3-i2); \
  if(rb!=ri){ bad++; put_s(" MISMATCH"); } put_s("\n"); }while(0)
asm(".section .text.init\n.globl _start\n_start:\nli sp, 0x80800000\ncall run\n");
void run(void){
  for(int i=0;i<NMAX;i++){ A32[i]=(u32)rnd(); A64[i]=rnd(); }
  static const size_t ns[] = {1,2,4,8,16,64,256,4096};
  static const u32 ds[] = {3,1000,65537,0x7FFFFFFFu};
  static const u64 ds64[] = {3,1000000007ULL,0x100000001ULL,0x7FFFFFFFFFFFFFFFULL};
  put_s("inv_div_probe v1\n");
  for(int rep=0;rep<2;rep++){
    put_s("rep "); put_u(rep); put_s("\n");
    for(unsigned k=0;k<sizeof ds/sizeof ds[0];k++) for(unsigned j=0;j<sizeof ns/sizeof ns[0];j++){
      size_t n=ns[j]; u32 d=ds[k];
      BENCH("u32_div", base_u32_div(A32,n,d), inv_u32_div(A32,n,d), n, d);
      BENCH("u32_mod", base_u32_mod(A32,n,d), inv_u32_mod(A32,n,d), n, d);
      BENCH("u32_divmod", base_u32_divmod(A32,n,d), inv_u32_divmod(A32,n,d), n, d);
      BENCH("s32_div", base_s32_div((const s32*)A32,n,(s32)d), inv_s32_div((const s32*)A32,n,(s32)d), n, d);
      BENCH("u32_chain", base_u32_chain(12345u,n,d), inv_u32_chain(12345u,n,d), n, d);
    }
    for(unsigned k=0;k<sizeof ds64/sizeof ds64[0];k++) for(unsigned j=0;j<sizeof ns/sizeof ns[0];j++){
      size_t n=ns[j]; u64 d=ds64[k];
      BENCH("u64_div", base_u64_div(A64,n,d), inv_u64_div(A64,n,d), n, d);
      BENCH("u64_mod", base_u64_mod(A64,n,d), inv_u64_mod(A64,n,d), n, d);
    }
  }
  put_s("done mismatches="); put_u(bad); put_s("\n");
  tohost = 1; while(1){}
}
