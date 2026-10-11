/* Original instruction probes. Inline assembly fixes the operation sequence;
 * n must be a positive multiple of 32, width must be 1 or 8. */
#include <stdint.h>

#if PROBE_KIND == 0
#define OP(S) "mulw " S ", " S ", %[factor]\n\t"
#elif PROBE_KIND == 1
#define OP(S) "slliw %[tmp], " S ", 1\n\t" \
              "addw %[tmp], %[tmp], " S "\n\t" \
              "slliw %[tmp], %[tmp], 2\n\t" \
              "addw " S ", %[tmp], " S "\n\t"
#elif PROBE_KIND == 2
#define OP(S) "addiw " S ", " S ", 13\n\t"
#else
#define OP(S) "ld " S ", 0(" S ")\n\t"
#endif
#define TWICE(B) B B
#define FOUR(B) TWICE(TWICE(B))
#define EIGHT(B) TWICE(FOUR(B))
#define THIRTY_TWO(B) FOUR(EIGHT(B))
#define ALL_STATES OP("%[s0]") OP("%[s1]") OP("%[s2]") OP("%[s3]") \
                   OP("%[s4]") OP("%[s5]") OP("%[s6]") OP("%[s7]")
#define CONSTRAINTS \
  [s0] "+&r"(s0), [s1] "+&r"(s1), [s2] "+&r"(s2), [s3] "+&r"(s3), \
  [s4] "+&r"(s4), [s5] "+&r"(s5), [s6] "+&r"(s6), [s7] "+&r"(s7), [tmp] "=&r"(tmp)

static uint32_t probe_body(const uint32_t *data, uint32_t *out, int n, int width) {
  uint64_t s[8];
  for (int j = 0; j < 8; ++j) {
    s[j] = 0x1234u + (uint32_t)j;
#if PROBE_KIND == 3
    s[j] = (uint64_t)(uintptr_t)(((const uint64_t *)data) + j);
#else
    (void)data;
#endif
  }
#ifdef HOST_CHECK
  for (int i = 0; i < n; ++i) {
    int j = i % width;
#if PROBE_KIND < 2
    s[j] = (uint32_t)s[j] * 13u;
#elif PROBE_KIND == 2
    s[j] = (uint32_t)s[j] + 13u;
#else
    s[j] = *(const uint64_t *)(uintptr_t)s[j];
#endif
  }
#else
  uint64_t s0 = s[0], s1 = s[1], s2 = s[2], s3 = s[3];
  uint64_t s4 = s[4], s5 = s[5], s6 = s[6], s7 = s[7], tmp;
  uint64_t factor = 13;
  for (int block = 0; block < n / 32; ++block) {
    if (width == 1)
      __asm__ volatile(THIRTY_TWO(OP("%[s0]")) : CONSTRAINTS : [factor] "r"(factor) : "memory");
    else
      __asm__ volatile(FOUR(ALL_STATES) : CONSTRAINTS : [factor] "r"(factor) : "memory");
  }
  s[0] = s0; s[1] = s1; s[2] = s2; s[3] = s3;
  s[4] = s4; s[5] = s5; s[6] = s6; s[7] = s7;
  (void)tmp;
#endif
  uint32_t sum = 0;
  for (int j = 0; j < width; ++j) {
    out[j] = (uint32_t)s[j];
    sum += out[j];
  }
  return sum;
}
