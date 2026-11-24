#include <stdint.h>
#include <stddef.h>
#define NI __attribute__((noinline,noipa))
NI void k_u32_div(uint32_t *o, const uint32_t *a, size_t n, uint32_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]/d; }
NI void k_u32_mod(uint32_t *o, const uint32_t *a, size_t n, uint32_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]%d; }
NI void k_s32_div(int32_t *o, const int32_t *a, size_t n, int32_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]/d; }
NI void k_s32_mod(int32_t *o, const int32_t *a, size_t n, int32_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]%d; }
NI void k_u64_div(uint64_t *o, const uint64_t *a, size_t n, uint64_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]/d; }
NI void k_u64_mod(uint64_t *o, const uint64_t *a, size_t n, uint64_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]%d; }
NI void k_s64_div(int64_t *o, const int64_t *a, size_t n, int64_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]/d; }
NI void k_s64_mod(int64_t *o, const int64_t *a, size_t n, int64_t d){ for(size_t i=0;i<n;i++) o[i]=a[i]%d; }
