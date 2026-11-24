// Verilator testbench for hardfloat DivSqrtRecF64 as elaborated in FireSim
// MegaBOOM V3 (inside BOOM FDivSqrtUnit).  Inputs use hardfloat's recoded
// 65-bit format; only normal doubles are used so recoding is
// sign<<64 | (exp+1025)<<52 | frac.  Measures inValid(fire) -> outValid cycles
// for div and sqrt, and the gap until inReady returns; checks results against
// the host's IEEE double division / sqrt (round-to-nearest-even).
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include "VDivSqrtRecF64.h"
#include "verilated.h"

static VDivSqrtRecF64 *top;
static uint64_t cyc = 0;
static void tick() { top->clock = 0; top->eval(); top->clock = 1; top->eval(); cyc++; }

static void set65(VlWide<3> &w, unsigned __int128 v) {
  w[0] = (uint32_t)v; w[1] = (uint32_t)(v >> 32); w[2] = (uint32_t)(v >> 64) & 1;
}
static unsigned __int128 get65(const VlWide<3> &w) {
  return (unsigned __int128)w[0] | ((unsigned __int128)w[1] << 32) | ((unsigned __int128)(w[2] & 1) << 64);
}
static unsigned __int128 rec(double d) {
  uint64_t b; memcpy(&b, &d, 8);
  uint64_t s = b >> 63, e = (b >> 52) & 0x7ff, f = b & ((1ull << 52) - 1);
  return ((unsigned __int128)s << 64) | ((unsigned __int128)(e + 1025) << 52) | f;
}
static double unrec(unsigned __int128 r) {
  uint64_t s = (uint64_t)(r >> 64) & 1, e = (uint64_t)(r >> 52) & 0xfff, f = (uint64_t)r & ((1ull << 52) - 1);
  uint64_t b = (s << 63) | ((e - 1025) << 52) | f;
  double d; memcpy(&d, &b, 8); return d;
}

int main(int argc, char **argv) {
  Verilated::commandArgs(argc, argv);
  top = new VDivSqrtRecF64;
  top->reset = 1; top->io_inValid = 0; for (int i = 0; i < 5; i++) tick(); top->reset = 0; tick();
  std::mt19937_64 rng(262);
  std::uniform_real_distribution<double> u(0.5, 4.0);
  printf("op,a,b,cycles_fire_to_out,gap_out_to_ready,first_ready_before_out,ok\n");
  long bad = 0;
  for (int i = 0; i < 400; i++) {
    int sqrt = i & 1;
    double a = u(rng) * std::ldexp(1.0, (int)(rng() % 40) - 20), b = u(rng) * std::ldexp(1.0, (int)(rng() % 40) - 20);
    top->clock = 0; top->eval();
    int guard = 0;
    while (!(sqrt ? top->io_inReady_sqrt : top->io_inReady_div)) { tick(); top->clock = 0; top->eval(); if (++guard > 500) return 3; }
    top->io_inValid = 1; top->io_sqrtOp = sqrt; set65(top->io_a, rec(a)); set65(top->io_b, rec(sqrt ? a : b));
    top->io_roundingMode = 0; top->io_detectTininess = 1; top->eval();
    uint64_t fire = cyc;
    tick(); top->clock = 0; top->io_inValid = 0; top->eval();
    int64_t ready_after = -1;
    while (!(top->io_outValid_div || top->io_outValid_sqrt)) {
      if (ready_after < 0 && (sqrt ? top->io_inReady_sqrt : top->io_inReady_div)) ready_after = (int64_t)(cyc - fire);
      tick(); top->clock = 0; top->eval(); if (++guard > 500) return 4; }
    uint64_t outc = cyc;
    double got = unrec(get65(top->io_out));
    double exp = sqrt ? std::sqrt(a) : a / b;
    int ok = (got == exp);
    if (!ok) bad++;
    tick(); top->clock = 0; top->eval();
    uint64_t gap = 1;
    while (!(sqrt ? top->io_inReady_sqrt : top->io_inReady_div)) { tick(); top->clock = 0; top->eval(); gap++; }
    printf("%s,%.17g,%.17g,%llu,%llu,%lld,%d\n", sqrt ? "sqrt" : "div", a, b,
           (unsigned long long)(outc - fire), (unsigned long long)gap, (long long)ready_after, ok);
  }
  fprintf(stderr, "fdiv mismatches=%ld\n", bad);
  delete top;
  return bad ? 1 : 0;
}
