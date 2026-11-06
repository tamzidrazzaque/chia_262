/* Diagnostic adapter only. Does not modify the traced executable or registers. */
#define _GNU_SOURCE
#include <sys/ptrace.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/uio.h>
#include <signal.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <elf.h>
#ifndef NT_RISCV_VECTOR
#define NT_RISCV_VECTOR 0x901
#endif
static void fail(const char *s) { perror(s); exit(125); }
static void save(const char *dir, const char *name, const void *data, size_t size) {
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/%s", dir, name) >= (int)sizeof(path)) exit(125);
    int fd = open(path, O_WRONLY|O_CREAT|O_EXCL, 0600);
    if (fd < 0) fail("create snapshot");
    const char *p = data;
    while (size) { ssize_t n = write(fd, p, size); if (n <= 0) fail("snapshot write"); p += n; size -= n; }
    if (fsync(fd) || close(fd)) fail("snapshot sync");
}
int main(int argc, char **argv) {
    if (argc < 3) return 125;
    pid_t child = fork(); if (child < 0) fail("fork");
    if (!child) {
        if (ptrace(PTRACE_TRACEME, 0, 0, 0)) fail("traceme");
        execvp(argv[2], argv + 2); fail("exec");
    }
    int status;
    if (waitpid(child, &status, 0) != child || !WIFSTOPPED(status) || WSTOPSIG(status) != SIGTRAP) fail("exec stop");
    if (ptrace(PTRACE_SETOPTIONS, child, 0, PTRACE_O_EXITKILL)) fail("exitkill");
    int deliver = 0, captured = 0;
    for (;;) {
        if (ptrace(PTRACE_CONT, child, 0, deliver)) fail("continue");
        if (waitpid(child, &status, 0) != child) fail("wait");
        if (WIFEXITED(status)) return WEXITSTATUS(status);
        if (WIFSIGNALED(status)) return WTERMSIG(status);
        if (!WIFSTOPPED(status)) return 125;
        deliver = WSTOPSIG(status);
        if (!captured && (deliver == SIGSEGV || deliver == SIGBUS || deliver == SIGILL)) {
            siginfo_t info; memset(&info, 0, sizeof(info));
            if (ptrace(PTRACE_GETSIGINFO, child, 0, &info)) fail("siginfo");
            save(argv[1], "fault.siginfo", &info, sizeof(info));
            unsigned char regs[4096] = {0}; struct iovec iov = {regs, sizeof(regs)};
            if (ptrace(PTRACE_GETREGSET, child, NT_PRSTATUS, &iov)) fail("gpr");
            save(argv[1], "fault.gpr", regs, iov.iov_len);
            memset(regs, 0, sizeof(regs)); iov.iov_len = sizeof(regs); errno = 0;
            int vr = ptrace(PTRACE_GETREGSET, child, NT_RISCV_VECTOR, &iov), ve = errno;
            if (vr == 0) save(argv[1], "fault.vector", regs, iov.iov_len);
            char meta[160];
            int n = snprintf(meta, sizeof(meta), "{\"signal\":%d,\"si_code\":%d,\"vector_errno\":%d,\"captured_before_delivery\":true}\n", info.si_signo, info.si_code, vr ? ve : 0);
            save(argv[1], "fault.meta.json", meta, n);
            captured = 1;
        }
    }
}
