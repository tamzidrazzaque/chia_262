// Verilator testbench for rocket-chip MulDiv exactly as elaborated inside the
// FireSim MegaBOOM V3 design (BOOM DivUnit instance, MulDivParams from the
// config).  Reads vectors "fn dw in1 in2" (fn/dw decimal, in1/in2 hex) from
// argv[1]; for each vector it fires one request when io_req_ready is high and
// counts cycles until io_resp_valid (resp.ready held high).  Prints CSV:
//   fn,dw,in1,in2,cycles_fire_to_resp,data,expected,ok,ready_gap
// cycles_fire_to_resp: number of clock edges from the cycle in which
// req.fire is true to the first cycle in which resp.valid is true.
// ready_gap: cycles from the resp.fire cycle to the next cycle with req.ready.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include "VMulDiv.h"
#include "verilated.h"

static VMulDiv *top;
static uint64_t cyc = 0;

static void tick() {
  top->clock = 0; top->eval();
  top->clock = 1; top->eval();
  cyc++;
}

static uint64_t sext32(uint64_t x) { return (uint64_t)(int64_t)(int32_t)(uint32_t)x; }

// RISC-V M-extension reference semantics.  fn: 4=DIV 5=DIVU 6=REM 7=REMU.
static uint64_t ref(int fn, int dw, uint64_t a, uint64_t b) {
  if (dw == 1) {
    int64_t sa = (int64_t)a, sb = (int64_t)b;
    switch (fn) {
      case 4: if (b == 0) return ~0ull; if (sa == INT64_MIN && sb == -1) return a; return (uint64_t)(sa / sb);
      case 5: if (b == 0) return ~0ull; return a / b;
      case 6: if (b == 0) return a; if (sa == INT64_MIN && sb == -1) return 0; return (uint64_t)(sa % sb);
      case 7: if (b == 0) return a; return a % b;
    }
  } else {
    int32_t sa = (int32_t)a, sb = (int32_t)b;
    uint32_t ua = (uint32_t)a, ub = (uint32_t)b;
    switch (fn) {
      case 4: if (ub == 0) return ~0ull; if (sa == INT32_MIN && sb == -1) return sext32(ua); return sext32((uint32_t)(sa / sb));
      case 5: if (ub == 0) return ~0ull; return sext32(ua / ub);
      case 6: if (ub == 0) return sext32(ua); if (sa == INT32_MIN && sb == -1) return 0; return sext32((uint32_t)(sa % sb));
      case 7: if (ub == 0) return sext32(ua); return sext32(ua % ub);
    }
  }
  return 0xdeadbeef;
}

int main(int argc, char **argv) {
  Verilated::commandArgs(argc, argv);
  if (argc < 2) { fprintf(stderr, "usage: %s vectors.txt\n", argv[0]); return 2; }
  FILE *vf = fopen(argv[1], "r");
  if (!vf) { perror("vectors"); return 2; }
  top = new VMulDiv;
  top->io_req_valid = 0; top->io_kill = 0; top->io_resp_ready = 1;
  top->reset = 1; for (int i = 0; i < 5; i++) tick(); top->reset = 0; tick();
  printf("fn,dw,in1,in2,cycles_fire_to_resp,data,expected,ok,ready_gap\n");
  int fn, dw; unsigned long long a, b; long n = 0, bad = 0;
  while (fscanf(vf, "%d %d %llx %llx", &fn, &dw, &a, &b) == 4) {
    // wait for ready (combinational from state)
    int guard = 0;
    top->clock = 0; top->eval();
    while (!top->io_req_ready) { tick(); top->clock = 0; top->eval(); if (++guard > 1000) { fprintf(stderr, "stuck\n"); return 1; } }
    top->io_req_valid = 1; top->io_req_bits_fn = fn; top->io_req_bits_dw = dw;
    top->io_req_bits_in1 = a; top->io_req_bits_in2 = b; top->io_req_bits_tag = 0;
    top->eval();
    uint64_t fire_cyc = cyc;  // req.fire is true during this cycle
    tick();
    top->io_req_valid = 0; top->eval();
    while (!top->io_resp_valid) { tick(); top->clock = 0; top->eval(); if (++guard > 1000) { fprintf(stderr, "no resp\n"); return 1; } }
    uint64_t resp_cyc = cyc;  // resp.valid (and fire, ready=1) this cycle
    uint64_t data = top->io_resp_bits_data;
    tick(); top->clock = 0; top->eval();
    uint64_t gap = 1;
    while (!top->io_req_ready) { tick(); top->clock = 0; top->eval(); gap++; }
    uint64_t exp = ref(fn, dw, a, b);
    int ok = (data == exp);
    if (!ok) bad++;
    n++;
    printf("%d,%d,%016llx,%016llx,%llu,%016llx,%016llx,%d,%llu\n", fn, dw, a, b,
           (unsigned long long)(resp_cyc - fire_cyc), (unsigned long long)data,
           (unsigned long long)exp, ok, (unsigned long long)gap);
  }
  fprintf(stderr, "vectors=%ld mismatches=%ld\n", n, bad);
  top->final();
  delete top;
  return bad ? 1 : 0;
}
