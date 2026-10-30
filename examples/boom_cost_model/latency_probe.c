/* Small dependency/throughput probes, independent of licensed benchmarks.
 * Includes loop/timer overhead: use comparisons, not exact latency claims.
 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>

static uint64_t monotonic_ns(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return 0;
    return (uint64_t)now.tv_sec * 1000000000 + now.tv_nsec;
}

static inline uint64_t reference(int operation, uint64_t value) {
    if (operation == 0) return value + 31;
    if (operation == 1) return value * 3;
    return value / 7 + UINT64_C(0xc000000000000001);
}

static inline uint64_t execute(int operation, uint64_t value) {
#ifdef __riscv
    uint64_t operand;
    if (operation == 0) {
        operand = 31;
        __asm__ volatile ("add %0,%0,%1" : "+r" (value) : "r" (operand));
    } else if (operation == 1) {
        operand = 3;
        __asm__ volatile ("mul %0,%0,%1" : "+r" (value) : "r" (operand));
    } else {
        operand = 7;
        __asm__ volatile ("divu %0,%0,%1" : "+r" (value) : "r" (operand));
        value += UINT64_C(0xc000000000000001);
    }
    return value;
#else
    return reference(operation, value);
#endif
}

int main(void) {
    const unsigned iterations = 100000;
    const char *names[] = {"add", "multiply", "divide"};
    for (int operation = 0; operation < 3; ++operation) {
        for (int chains = 1; chains <= 4; chains += 3) {
            uint64_t actual[4] = {17, 19, 23, 29};
            uint64_t expected[4] = {17, 19, 23, 29};
            uint64_t begin = monotonic_ns();
            for (unsigned i = 0; i < iterations; ++i) {
                if (chains == 1) {
                    actual[0] = execute(operation, actual[0]);
                    actual[0] = execute(operation, actual[0]);
                    actual[0] = execute(operation, actual[0]);
                    actual[0] = execute(operation, actual[0]);
                } else {
                    actual[0] = execute(operation, actual[0]);
                    actual[1] = execute(operation, actual[1]);
                    actual[2] = execute(operation, actual[2]);
                    actual[3] = execute(operation, actual[3]);
                }
            }
            uint64_t elapsed = monotonic_ns() - begin;
            for (unsigned i = 0; i < iterations; ++i)
                for (int j = 0; j < 4; ++j) {
                    int index = chains == 1 ? 0 : j;
                    expected[index] = reference(operation, expected[index]);
                }
            int correct = 1;
            uint64_t checksum = 0;
            for (int j = 0; j < 4; ++j) {
                correct &= actual[j] == expected[j];
                checksum ^= actual[j];
            }
            printf("{\"operation\":\"%s\",\"chains\":%d,\"elapsed_ns\":%" PRIu64
                   ",\"operations\":%u,\"checksum\":%" PRIu64 ",\"correct\":%s}\n",
                   names[operation], chains, elapsed, iterations * 4, checksum,
                   correct ? "true" : "false");
            if (!correct) return 1;
        }
    }
    return 0;
}
