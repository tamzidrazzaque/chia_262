.text
.globl vector_andn
.type vector_andn, @function
vector_andn:
    vandn.vv v0, v1, v2
    ret
.size vector_andn, .-vector_andn
