# MegaBOOM latency/throughput microbenchmark suite.
#   make            -> generate + build all group ELFs into build/
#   make spike      -> functional (checksum) validation on spike; spike cycles are NOT timing
#   make clean
# Builds are cheap; keep -j <= 8 on shared hosts.

RVCC    ?= /scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-gcc
OBJDUMP ?= /scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-objdump
SPIKE   ?= /scratch/trazzaque/riscv-isa-sim-local/bin/spike
PYTHON  ?= python3
GCC_REF ?= /home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc

B       := build
GROUPS  := int div64 div32 fpmem divconst hide loopdiv smoke
ELFS    := $(addprefix $(B)/mb_,$(addsuffix .elf,$(GROUPS)))
CFLAGS  := -march=rv64gc -mabi=lp64d -mcmodel=medany -O2 -ffreestanding -fno-builtin \
           -fno-common -nostdlib -nostartfiles -Wall
LDFLAGS := -T common/link.ld -Wl,--no-relax -Wl,--no-warn-rwx-segments -static

all: $(ELFS) $(B)/dumps.stamp

# gccref/divc.gcc15.s is the checked-in GCC 15.1 (g1b306039a) -O2 output used to
# extract the exact div-by-constant sequences; 'make gccref' regenerates it.
gccref:
	$(GCC_REF) -O2 -march=rv64gc -mabi=lp64d -S gccref/divc.c -o gccref/divc.gcc15.s

$(B)/manifest.json: gen/gen.py gen/rvmodel.py gccref/divc.gcc15.s
	$(PYTHON) gen/gen.py --out $(B) --gcc-ref gccref/divc.gcc15.s

$(B)/%_kernels.S $(B)/%_table.c: $(B)/manifest.json ;

$(B)/mb_%.elf: $(B)/%_kernels.S $(B)/%_table.c common/harness.c common/crt.S common/link.ld
	$(RVCC) $(CFLAGS) $(LDFLAGS) -o $@ common/crt.S common/harness.c $(B)/$*_table.c $(B)/$*_kernels.S -lgcc

$(B)/dumps.stamp: $(ELFS)
	for e in $(ELFS); do $(OBJDUMP) -d $$e > $${e%.elf}.dump; done
	touch $@

check: $(B)/dumps.stamp
	$(PYTHON) check_dump.py $(B)

spike: $(ELFS)
	./run.sh $(SPIKE) --spike --out results/spike

clean:
	rm -f $(B)/*.elf $(B)/*.dump $(B)/*.S $(B)/*.c $(B)/manifest.json $(B)/gen.log $(B)/dumps.stamp

.PHONY: all check spike clean gccref
# generated sources are not intermediates: keep them
.SECONDARY:
