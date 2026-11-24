/* Bare-metal HTIF image for chipyard Verilator / FireSim / spike.
   Derived from campaign/div_probe.ld; adds bss bounds and a private stack. */
OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS
{
  . = 0x80000000;
  .text.init : { *(.text.init) }
  .text : { *(.text) *(.text.*) }
  . = ALIGN(65536); /* rtl-tune review: data at a fixed address regardless of kernel size */
  .rodata : { *(.rodata) *(.rodata.*) *(.srodata) *(.srodata.*) }
  . = ALIGN(64);
  .data : { *(.data) *(.data.*) *(.sdata) *(.sdata.*) }
  . = ALIGN(64);
  _bss_start = .;
  .bss : { *(.sbss) *(.sbss.*) *(.bss) *(.bss.*) *(COMMON) }
  . = ALIGN(64);
  _bss_end = .;
  . = ALIGN(64);
  .tohost : { *(.tohost) }
  . = ALIGN(64);
  .fromhost : { *(.fromhost) }
  . = ALIGN(4096);
  _end = .;
  /* 64 KiB stack above the image, symbol only: no segment, so the loader
     (fesvr over TSI on Verilator) does not have to zero-fill it. */
  _stack_top = _end + 0x10000;
  /DISCARD/ : { *(.eh_frame) *(.comment) *(.riscv.attributes) }
}
