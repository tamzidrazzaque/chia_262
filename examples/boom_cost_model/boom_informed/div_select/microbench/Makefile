# Range-aware division microbenchmarks.  Reuses ../../microbench/common (read-only).
RVCC    ?= /scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-gcc
OBJDUMP ?= /scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-objdump
SPIKE   ?= /scratch/trazzaque/riscv-isa-sim-local/bin/spike
COMMON  := ../../microbench/common
B       := build
GROUPS  ?= rdsmoke rdseq rdgrid rdrange64 rdrange32
ELFS    := $(addprefix $(B)/,$(addsuffix .elf,$(GROUPS)))
CFLAGS  := -march=rv64gc -mabi=lp64d -mcmodel=medany -O2 -ffreestanding -fno-builtin \
           -fno-common -nostdlib -nostartfiles -Wall -DMB_REPS=2
LDFLAGS := -T $(COMMON)/link.ld -Wl,--no-relax -Wl,--no-warn-rwx-segments -static

all: $(ELFS)

$(B)/manifest.json: gen_rd.py gccref/rdc.rocket.s
	python3 gen_rd.py --out $(B)

$(B)/%_kernels.S $(B)/%_table.c: $(B)/manifest.json ;

$(B)/%.elf: $(B)/%_kernels.S $(B)/%_table.c $(COMMON)/harness.c $(COMMON)/crt.S
	$(RVCC) $(CFLAGS) $(LDFLAGS) -o $@ $(COMMON)/crt.S $(COMMON)/harness.c $(B)/$*_table.c $(B)/$*_kernels.S -lgcc
	$(OBJDUMP) -d $@ > $(B)/$*.dump

spike: $(ELFS)
	mkdir -p results/spike
	for e in $(ELFS); do $(SPIKE) --isa=rv64gc_zicntr $$e > results/spike/$$(basename $$e .elf).log 2>&1; echo "$$e rc=$$?"; done

.SECONDARY:
.PHONY: all spike
