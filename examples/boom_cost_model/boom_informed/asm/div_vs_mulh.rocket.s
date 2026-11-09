	.file	"div_vs_mulh.c"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_zicsr2p0_zifencei2p0_zmmul1p0_zaamo1p0_zalrsc1p0_zca1p0_zcd1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	udiv_const
	.type	udiv_const, @function
udiv_const:
.LFB0:
	.cfi_startproc
	li	a4,806912
	addi	a4,a4,-315
	li	a5,660762624
	slli	a4,a4,12
	addi	a5,a5,1575
	addi	a4,a4,-315
	slli	a5,a5,33
	add	a5,a5,a4
	mulhu	a0,a0,a5
	srli	a0,a0,2
	ret
	.cfi_endproc
.LFE0:
	.size	udiv_const, .-udiv_const
	.align	1
	.globl	sdiv_const
	.type	sdiv_const, @function
sdiv_const:
.LFB1:
	.cfi_startproc
	li	a4,806912
	addi	a4,a4,-315
	li	a5,660762624
	slli	a4,a4,12
	addi	a5,a5,1575
	addi	a4,a4,-315
	slli	a5,a5,33
	add	a5,a5,a4
	mulh	a5,a0,a5
	srai	a0,a0,63
	srai	a5,a5,2
	sub	a0,a5,a0
	ret
	.cfi_endproc
.LFE1:
	.size	sdiv_const, .-sdiv_const
	.align	1
	.globl	udiv_var
	.type	udiv_var, @function
udiv_var:
.LFB2:
	.cfi_startproc
	divu	a0,a0,a1
	ret
	.cfi_endproc
.LFE2:
	.size	udiv_var, .-udiv_var
	.align	1
	.globl	urem_var
	.type	urem_var, @function
urem_var:
.LFB3:
	.cfi_startproc
	remu	a0,a0,a1
	ret
	.cfi_endproc
.LFE3:
	.size	urem_var, .-urem_var
	.align	1
	.globl	force_div
	.type	force_div, @function
force_div:
.LFB4:
	.cfi_startproc
#APP
# 18 "/scratch/trazzaque/chia_262/examples/boom_cost_model/boom_informed/div_vs_mulh.c" 1
	divu a0, a0, a1
# 0 "" 2
#NO_APP
	ret
	.cfi_endproc
.LFE4:
	.size	force_div, .-force_div
	.align	1
	.globl	force_mulh_magic
	.type	force_mulh_magic, @function
force_mulh_magic:
.LFB5:
	.cfi_startproc
	li	a4,806912
	addi	a4,a4,-315
	li	a5,660762624
	slli	a4,a4,12
	addi	a5,a5,1575
	addi	a4,a4,-315
	slli	a5,a5,33
	add	a5,a5,a4
#APP
# 25 "/scratch/trazzaque/chia_262/examples/boom_cost_model/boom_informed/div_vs_mulh.c" 1
	mulhu a0, a0, a5
# 0 "" 2
#NO_APP
	srli	a0,a0,2
	ret
	.cfi_endproc
.LFE5:
	.size	force_mulh_magic, .-force_mulh_magic
	.ident	"GCC: (g1b306039a) 15.1.0"
	.section	.note.GNU-stack,"",@progbits
