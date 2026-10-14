/* Per-process bind policy for the pinned, dynamically linked Ray runtime.
 * This is listener configuration, not an isolation boundary for hostile code.
 * Wildcard Internet binds become the configured loopback address; explicit
 * non-loopback binds fail. Unix sockets and outbound connections are unchanged.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

static int (*real_bind)(int, const struct sockaddr *, socklen_t);
static struct in_addr loopback;
static int valid_policy;
static unsigned int ephemeral_min, ephemeral_max;
static pthread_once_t once = PTHREAD_ONCE_INIT;

static void initialize(void) {
    const char *ip = getenv("CHIA_LOOPBACK_BIND_IP");
    real_bind = dlsym(RTLD_NEXT, "bind");
    valid_policy = ip && inet_pton(AF_INET, ip, &loopback) == 1 &&
        (ntohl(loopback.s_addr) >> 24) == 127 && real_bind;
    const char *low = getenv("CHIA_LOOPBACK_PORT_MIN");
    const char *high = getenv("CHIA_LOOPBACK_PORT_MAX");
    if (low || high) {
        char *end_low = NULL, *end_high = NULL;
        unsigned long a = low ? strtoul(low, &end_low, 10) : 0;
        unsigned long b = high ? strtoul(high, &end_high, 10) : 0;
        if (!a || a > b || b > 65535 || !end_low || *end_low ||
            !end_high || *end_high) valid_policy = 0;
        else { ephemeral_min = a; ephemeral_max = b; }
    }
}

/* The launcher checks this symbol and actual wildcard bind behavior first. */
int chia_loopback_guard_ready(void) {
    pthread_once(&once, initialize);
    return valid_policy;
}

static int bounded_bind(int fd, struct sockaddr *addr, socklen_t length,
                        in_port_t *port) {
    if (*port || !ephemeral_min) return real_bind(fd, addr, length);
    /* Pin dynamically allocated driver RPCs to the SSH-forwarded port block. */
    for (unsigned int p = ephemeral_min; p <= ephemeral_max; ++p) {
        *port = htons(p);
        int result = real_bind(fd, addr, length);
        if (result == 0 || errno != EADDRINUSE) return result;
    }
    errno = EADDRINUSE;
    return -1;
}

int bind(int fd, const struct sockaddr *addr, socklen_t length) {
    pthread_once(&once, initialize);
    if (!real_bind || !valid_policy) {
        errno = EACCES;
        return -1;
    }
    if (!addr) return real_bind(fd, addr, length);
    if (addr->sa_family == AF_INET && length >= sizeof(struct sockaddr_in)) {
        struct sockaddr_in local;
        memcpy(&local, addr, sizeof(local));
        if (local.sin_addr.s_addr == htonl(INADDR_ANY))
            local.sin_addr = loopback;
        else if ((ntohl(local.sin_addr.s_addr) >> 24) != 127) {
            errno = EACCES;
            return -1;
        }
        return bounded_bind(fd, (struct sockaddr *)&local, sizeof(local),
                            &local.sin_port);
    }
    if (addr->sa_family == AF_INET6 && length >= sizeof(struct sockaddr_in6)) {
        struct sockaddr_in6 local;
        memcpy(&local, addr, sizeof(local));
        if (IN6_IS_ADDR_UNSPECIFIED(&local.sin6_addr)) {
            int v6_only = 0;
            socklen_t size = sizeof(v6_only);
            if (getsockopt(fd, IPPROTO_IPV6, IPV6_V6ONLY, &v6_only, &size))
                return -1;
            if (v6_only) local.sin6_addr = in6addr_loopback;
            else {
                memset(&local.sin6_addr, 0, sizeof(local.sin6_addr));
                local.sin6_addr.s6_addr[10] = 0xff;
                local.sin6_addr.s6_addr[11] = 0xff;
                memcpy(&local.sin6_addr.s6_addr[12], &loopback, 4);
            }
        } else if (!IN6_IS_ADDR_LOOPBACK(&local.sin6_addr)) {
            uint32_t mapped;
            memcpy(&mapped, &local.sin6_addr.s6_addr[12], 4);
            if (!IN6_IS_ADDR_V4MAPPED(&local.sin6_addr) ||
                (ntohl(mapped) >> 24) != 127) {
                errno = EACCES;
                return -1;
            }
        }
        return bounded_bind(fd, (struct sockaddr *)&local, sizeof(local),
                            &local.sin6_port);
    }
    return real_bind(fd, addr, length);
}
