.section .text.init
.globl _start
.type _start, @function
_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    li t0, 0x200
    csrs mstatus, t0
    vsetivli zero, 4, e32, m1, ta, ma

    la t0, input_a
    vle32.v v1, (t0)
    la t0, input_b
    vle32.v v2, (t0)

    vadd.vv v3, v1, v2
    la t0, add_result
    vse32.v v3, (t0)

    vandn.vv v3, v2, v1
    la t0, andn_result
    vse32.v v3, (t0)

    la t0, add_result
    lwu t1, 0(t0)
    li t2, 0xffffffff
    bne t1, t2, fail
    lwu t1, 4(t0)
    li t2, 0x12345677
    bne t1, t2, fail
    lwu t1, 8(t0)
    li t2, 0xffffffff
    bne t1, t2, fail
    lwu t1, 12(t0)
    bne t1, t2, fail

    la t0, andn_result
    lwu t1, 0(t0)
    li t2, 0xffffffff
    bne t1, t2, fail
    lwu t1, 4(t0)
    li t2, 0
    bne t1, t2, fail
    lwu t1, 8(t0)
    li t2, 0xf0f0f0f0
    bne t1, t2, fail
    lwu t1, 12(t0)
    li t2, 0xaaaaaaaa
    bne t1, t2, fail

    li t0, 1
    j finish
fail:
    li t0, 3
finish:
    la t1, tohost
    sd t0, 0(t1)
1:
    j 1b
.size _start, .-_start

.section .rodata
.align 2
input_a:
    .word 0x00000000, 0xffffffff, 0x0f0f0f0f, 0x55555555
input_b:
    .word 0xffffffff, 0x12345678, 0xf0f0f0f0, 0xaaaaaaaa

.section .data
.align 2
add_result:
    .zero 16
andn_result:
    .zero 16

.section .tohost,"aw",@progbits
.align 3
.globl tohost
tohost:
    .dword 0
.globl fromhost
fromhost:
    .dword 0
