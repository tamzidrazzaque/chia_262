/* Minimal M-mode start: FPU on, fcsr=0 (RNE), bss zeroed, trap reporter. */
  .section .text.init
  .globl _start
_start:
  csrr  t0, mhartid
  bnez  t0, 9f
  la    t0, trap_entry
  csrw  mtvec, t0
  li    t0, 0x6000          /* mstatus.FS = dirty */
  csrs  mstatus, t0
  csrwi fcsr, 0
  la    sp, _stack_top
  la    t0, _bss_start
  la    t1, _bss_end
1:bgeu  t0, t1, 2f
  sd    zero, 0(t0)
  addi  t0, t0, 8
  j     1b
2:call  main
  /* exit code a0 -> tohost = (a0 << 1) | 1 */
  slli  a0, a0, 1
  ori   a0, a0, 1
  la    t0, tohost
  sd    a0, 0(t0)
3:j     3b
9:wfi
  j     9b

  .balign 4
trap_entry:                 /* any trap: exit code 1000 + mcause */
  csrr  a0, mcause
  addi  a0, a0, 1000
  slli  a0, a0, 1
  ori   a0, a0, 1
  la    t0, tohost
  sd    a0, 0(t0)
4:j     4b
