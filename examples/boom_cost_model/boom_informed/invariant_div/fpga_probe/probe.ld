OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS
{
  . = 0x80000000;
  .text : { *(.text.init) *(.text) *(.text.*) }
  .rodata : { *(.rodata) *(.rodata.*) }
  .data : { *(.data) *(.data.*) }
  .sdata : { *(.sdata) *(.sdata.*) }
  .bss : { *(.sbss) *(.bss) *(.bss.*) *(COMMON) }
  . = ALIGN(0x40);
  .tohost : { *(.tohost) }
  . = ALIGN(0x40);
  .fromhost : { *(.fromhost) }
  /DISCARD/ : { *(.eh_frame) *(.comment) }
}
