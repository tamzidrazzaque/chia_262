// Verilator testbench for rocket PipelinedMultiplier as elaborated in FireSim
// MegaBOOM V3 (BOOM PipelinedMulUnit, numStages = imulLatency).  Measures
// req.valid -> resp.valid latency and checks one new request per cycle
// (initiation interval 1) with result checking for MUL/MULH/MULHSU/MULHU/MULW.
#include <cstdint>
#include <cstdio>
#include <deque>
#include <random>
#include "VPipelinedMultiplier.h"
#include "verilated.h"

static VPipelinedMultiplier *top;
static void tick() { top->clock = 0; top->eval(); top->clock = 1; top->eval(); }

static uint64_t ref(int fn, int dw, uint64_t a, uint64_t b) {
  __int128 sa = (__int128)(int64_t)a, sb = (__int128)(int64_t)b;
  unsigned __int128 ua = a, ub = b;
  switch (fn) {
    case 0: if (dw == 0) return (uint64_t)(int64_t)(int32_t)(uint32_t)(a * b); return a * b;
    case 1: return (uint64_t)((sa * sb) >> 64);
    case 2: return (uint64_t)((sa * (__int128)ub) >> 64);
    case 3: return (uint64_t)((ua * ub) >> 64);
  }
  return 0;
}

int main(int argc, char **argv) {
  Verilated::commandArgs(argc, argv);
  top = new VPipelinedMultiplier;
  top->reset = 1; top->io_req_valid = 0; for (int i = 0; i < 4; i++) tick(); top->reset = 0;
  // single-shot latency
  top->clock = 0; top->io_req_valid = 1; top->io_req_bits_fn = 0; top->io_req_bits_dw = 1;
  top->io_req_bits_in1 = 3; top->io_req_bits_in2 = 5; top->eval();
  tick(); top->clock = 0; top->io_req_valid = 0; top->eval();
  int lat = 1; while (!top->io_resp_valid && lat < 50) { tick(); top->clock = 0; top->eval(); lat++; }
  printf("single_latency_cycles,%d,data=%llu\n", lat, (unsigned long long)top->io_resp_bits_data);
  for (int i = 0; i < 10; i++) tick();
  // streaming: one request per cycle, check every result in order
  std::mt19937_64 rng(262);
  std::deque<uint64_t> expq; long n = 0, bad = 0, issued = 0; int firstresp = -1;
  for (int c = 0; c < 3000; c++) {
    top->clock = 0;
    if (top->io_resp_valid) {
      if (firstresp < 0) firstresp = c;
      uint64_t e = expq.front(); expq.pop_front(); n++;
      if (top->io_resp_bits_data != e) bad++;
    }
    if (c < 2000) {
      int fn = rng() % 4, dw = (fn == 0) ? (int)(rng() % 2) : 1;
      uint64_t a = rng(), b = rng();
      top->io_req_valid = 1; top->io_req_bits_fn = fn; top->io_req_bits_dw = dw;
      top->io_req_bits_in1 = a; top->io_req_bits_in2 = b;
      expq.push_back(ref(fn, dw, a, b)); issued++;
    } else top->io_req_valid = 0;
    top->eval();
    tick();
  }
  printf("stream_issued,%ld,stream_checked,%ld,mismatches,%ld,first_resp_cycle,%d\n", issued, n, bad, firstresp);
  delete top;
  return bad ? 1 : 0;
}
