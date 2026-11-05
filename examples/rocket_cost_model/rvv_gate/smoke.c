/* Platform correctness gate: RVV loads/add/stores, VLEN and target cycles. */
#include <stdint.h>
#include <stdio.h>
#include <sys/auxv.h>

static unsigned long cycles(void) {
    unsigned long value;
    __asm__ volatile ("rdcycle %0" : "=r"(value));
    return value;
}

static int check(unsigned long count) {
    uint32_t a[8], b[8], result[9];
    for (unsigned i = 0; i < 8; ++i) {
        a[i] = UINT32_MAX - i;
        b[i] = 3 * i + 7;
        result[i] = 0xdeadbeef;
    }
    result[8] = 0xdeadbeef;
    unsigned long vl;
    __asm__ volatile (
        "vsetvli %[vl], %[count], e32, m1, ta, ma\n\t"
        "vle32.v v1, (%[a])\n\t"
        "vle32.v v2, (%[b])\n\t"
        "vadd.vv v3, v1, v2\n\t"
        "vse32.v v3, (%[out])"
        : [vl] "=&r"(vl)
        : [count] "r"(count), [a] "r"(a), [b] "r"(b), [out] "r"(result)
        : "memory", "v1", "v2", "v3");
    if (vl != count) return 1;
    for (unsigned i = 0; i < 9; ++i) {
        uint32_t expected = i < count ? a[i] + b[i] : 0xdeadbeef;
        if (result[i] != expected) return 2;
    }
    return 0;
}

int main(void) {
    if (!(getauxval(AT_HWCAP) & (1UL << ('V' - 'A')))) {
        puts("RVV_GATE_FAIL missing Linux V capability");
        return 1;
    }
    unsigned long bytes;
    __asm__ volatile ("csrr %0, vlenb" : "=r"(bytes));
    printf("RVV_GATE_VLEN_BITS=%lu\n", bytes * 8);
    if (bytes != 32) return 2;
    unsigned long before = cycles();
    int full = check(8), tail = check(3);
    unsigned long after = cycles();
    printf("RVV_GATE_FULL=%d RVV_GATE_TAIL=%d\n", full, tail);
    printf("RVV_GATE_CYCLE_BEFORE=%lu\nRVV_GATE_CYCLE_AFTER=%lu\n", before, after);
    if (full || tail || after <= before) return 3;
    puts("RVV_GATE_PASS");
    return 0;
}
