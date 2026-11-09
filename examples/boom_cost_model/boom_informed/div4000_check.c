#include <stdio.h>
#include <stdint.h>

__attribute__((noinline)) long sdiv4000(long x) { return x / 4000; }
__attribute__((noinline)) long smod4000(long x) { return x % 4000; }
__attribute__((noinline)) long sdiv13(long x) { return x / 13; }

/* Dependent chain and several independent divisions. Both are constant
   divisions; the occupancy pass treats the divider as one held unit. */
__attribute__((noinline)) long dep_chain(long x) {
  x = x / 4000;
  x = x / 13;
  x = x / 4000;
  return x;
}

__attribute__((noinline)) long indep_sum(long a, long b, long c, long d) {
  return a / 4000 + b / 4000 + c / 13 + d / 4000;
}

static int check_div(long x) {
  long q = sdiv4000(x);
  long r = smod4000(x);
  long expect_q = x / 4000;
  long expect_r = x % 4000;
  if (q != expect_q || r != expect_r || q * 4000 + r != x) {
    printf("FAIL div4000 x=%ld q=%ld r=%ld\n", x, q, r);
    return 1;
  }
  if (sdiv13(x) != x / 13) {
    printf("FAIL div13 x=%ld\n", x);
    return 1;
  }
  return 0;
}

int main(void) {
  long samples[] = {0, 1, -1, 3999, 4000, -4000, -4001, 13, -13,
                    1000000, -1000000, 9223372036854775807L,
                    -9223372036854775807L};
  int bad = 0;
  for (unsigned i = 0; i < sizeof(samples) / sizeof(samples[0]); i++)
    bad += check_div(samples[i]);
  long dep = dep_chain(4000L * 13 * 4000 * 3);
  long indep = indep_sum(8000, -4000, 26, 12000);
  printf("dep=%ld indep=%ld bad=%d\n", dep, indep, bad);
  return bad ? 1 : 0;
}
