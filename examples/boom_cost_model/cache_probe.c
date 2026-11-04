/* Original cache-capacity diagnostic, independent of licensed workloads.
 * Fixed memory accesses test hardware sensitivity, not compiler speedups.
 */
#define _POSIX_C_SOURCE 200809L
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

struct node { uint64_t next, value, padding[6]; };
_Static_assert(sizeof(struct node) == 64, "one node per target cache line");
static volatile uint64_t sink;

static uint64_t now_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return 0;
    uint64_t value = (uint64_t)t.tv_sec * UINT64_C(1000000000) + t.tv_nsec;
#ifdef CACHE_TEST_TICK_NS
    value -= value % CACHE_TEST_TICK_NS;
#endif
    return value;
}

__attribute__((noinline, noclone, noipa))
static uint64_t chase(const volatile struct node *nodes, size_t count) {
    uint64_t sum = 0, p = 0;
    for (unsigned round = 0; round < 2; ++round)
        for (size_t i = 0; i < count; ++i) {
            p = nodes[p].next;
            sum += p;
        }
    return sum;
}

__attribute__((noinline, noclone, noipa))
static uint64_t stream(const volatile struct node *nodes, size_t count) {
    uint64_t sum = 0;
    for (unsigned round = 0; round < 2; ++round)
        for (size_t i = 0; i < count; ++i) sum += nodes[i].value;
    return sum;
}

int main(void) {
    const unsigned sizes_kib[] = {8, 16, 32, 64, 256, 1024, 4096, 16384};
    const char *names[] = {"chase", "stream"};
    uint64_t (*kernels[])(const volatile struct node *, size_t) = {chase, stream};
    for (unsigned s = 0; s < sizeof sizes_kib / sizeof sizes_kib[0]; ++s) {
        size_t bytes = (size_t)sizes_kib[s] * 1024, count = bytes / 64;
        struct node *nodes = aligned_alloc(64, bytes);
        uint32_t *order = malloc(count * sizeof *order);
        if (!nodes || !order) { free(nodes); free(order); return 1; }
        for (size_t i = 0; i < count; ++i) order[i] = (uint32_t)i;
        uint64_t random = UINT64_C(0x165667b19e3779f9);
        for (size_t i = count - 1; i > 0; --i) {
            random ^= random << 13; random ^= random >> 7; random ^= random << 17;
            size_t j = random % (i + 1);
            uint32_t temp = order[i]; order[i] = order[j]; order[j] = temp;
        }
        for (size_t i = 0; i < count; ++i) {
            nodes[order[i]].next = order[(i + 1) % count];
            nodes[i].value = i;
        }
        free(order);
        uint64_t expected = (uint64_t)count * (count - 1);
        for (unsigned k = 0; k < 2; ++k) {
            sink = kernels[k](nodes, count); /* Untimed traversal faults in pages. */
            unsigned calls = 1;
            for (;;) {
                uint64_t begin = now_ns(), checksum = 0;
                for (unsigned c = 0; c < calls; ++c) checksum += kernels[k](nodes, count);
                uint64_t end = now_ns();
                sink = checksum;
                if (!begin || end < begin || checksum != expected * calls) {
                    free(nodes); return 1;
                }
                /* Amortize timer quantization and loop overhead. QEMU cannot
                 * establish the guest clock granularity of the FPGA kernel. */
                if (end - begin >= UINT64_C(1000000)) break;
                if ((uint64_t)count * 2 * calls >= UINT64_C(33554432)) {
                    free(nodes); return 1;
                }
                calls *= 2;
            }
            for (unsigned repeat = 0; repeat < 3; ++repeat) {
                uint64_t begin = now_ns(), checksum = 0;
                for (unsigned c = 0; c < calls; ++c) checksum += kernels[k](nodes, count);
                uint64_t end = now_ns();
                sink = checksum;
                int correct = checksum == expected * calls && begin && end > begin;
                printf("{\"kernel\":\"%s\",\"working_set_bytes\":%zu,\"line_bytes\":64,"
                       "\"repeat\":%u,\"batch_calls\":%u,\"loads\":%zu,\"elapsed_ns\":%" PRIu64
                       ",\"checksum\":%" PRIu64 ",\"correct\":%s}\n",
                       names[k], bytes, repeat, calls, count * 2 * calls, end - begin, checksum,
                       correct ? "true" : "false");
                if (!correct) { free(nodes); return 1; }
            }
        }
        free(nodes);
    }
    return 0;
}
