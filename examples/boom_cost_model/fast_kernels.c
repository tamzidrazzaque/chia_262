/* Original, redistributable compiler-sensitive screening kernels.
 * These are proxies, not extracted SPEC code. Timers include loop overhead.
 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>

#define N 4096
#define ROUNDS 32
static uint64_t data[N];
static uint32_t next[N];
static volatile uint64_t sink;

static uint64_t ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return 0;
    return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}

__attribute__((noinline, noclone, noipa)) static uint64_t stream(void) {
    uint64_t x = 0;
    for (unsigned r = 0; r < ROUNDS; ++r)
        for (unsigned i = 0; i < N; ++i) x += data[i] * 7 + r;
    return x;
}
__attribute__((noinline, noclone, noipa)) static uint64_t branch(void) {
    uint64_t x = 1;
    for (unsigned r = 0; r < ROUNDS; ++r)
        for (unsigned i = 0; i < N; ++i)
            if (data[i] & 256) x += data[i] ^ r; else x ^= data[i] + r;
    return x;
}
__attribute__((noinline, noclone, noipa)) static uint64_t pointer(void) {
    uint32_t p = 0;
    uint64_t x = 0;
    for (unsigned i = 0; i < N * ROUNDS; ++i) { p = next[p]; x += data[p]; }
    return x;
}
__attribute__((noinline, noclone, noipa)) static uint64_t multiply(void) {
    uint64_t a = 17, b = 19, c = 23, d = 29;
    for (unsigned i = 0; i < N * ROUNDS; ++i) {
        a = a * 7 + i; b = b * 11 + i; c = c * 13 + i; d = d * 17 + i;
    }
    return a ^ b ^ c ^ d;
}
__attribute__((noinline, noclone, noipa)) static uint64_t divide(void) {
    uint64_t x = 0;
    for (unsigned r = 0; r < ROUNDS; ++r)
        for (unsigned i = 0; i < N; ++i) x += (data[i] + r * 65537) / ((data[(i+1) & (N-1)] & 31) + 1);
    return x;
}
__attribute__((noinline, noclone, noipa)) static uint64_t floating(void) {
    double a = 0, b = 0, c = 0, d = 0;
    for (unsigned r = 0; r < ROUNDS; ++r)
        for (unsigned i = 0; i < N; ++i) {
            double x = (double)(data[i] & 1023);
            a += x * 0.5; b += x * 0.25; c += x * 0.125; d += x * 0.0625;
        }
    return (uint64_t)((a+b+c+d) * 16.0);
}

int main(void) {
    uint64_t seed = 123;
    for (unsigned i = 0; i < N; ++i) {
        seed = seed * UINT64_C(6364136223846793005) + 1;
        data[i] = seed >> 32;
        next[i] = (i * 5 + 1) & (N-1);
    }
    uint64_t (*kernels[])(void) = {stream, branch, pointer, multiply, divide, floating};
    const char *names[] = {"stream", "branch", "pointer", "multiply", "divide", "floating"};
    for (unsigned k = 0; k < 6; ++k) {
        sink = kernels[k]();
        for (unsigned rep = 0; rep < 3; ++rep) {
            uint64_t begin = ns(), checksum = kernels[k](), end = ns();
            sink = checksum;
            printf("{\"kernel\":\"%s\",\"repeat\":%u,\"elapsed_ns\":%" PRIu64
                   ",\"checksum\":%" PRIu64 "}\n", names[k], rep, end-begin, checksum);
            if (!begin || end <= begin) return 1;
        }
    }
    return 0;
}
