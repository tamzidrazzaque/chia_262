#include <stddef.h>
#include <stdint.h>
#include <riscv_vector.h>

void vector_add_i32(size_t n, const int32_t *a, const int32_t *b, int32_t *out)
{
    while (n > 0) {
        size_t vl = __riscv_vsetvl_e32m1(n);
        vint32m1_t va = __riscv_vle32_v_i32m1(a, vl);
        vint32m1_t vb = __riscv_vle32_v_i32m1(b, vl);
        vint32m1_t sum = __riscv_vadd_vv_i32m1(va, vb, vl);
        __riscv_vse32_v_i32m1(out, sum, vl);

        a += vl;
        b += vl;
        out += vl;
        n -= vl;
    }
}
