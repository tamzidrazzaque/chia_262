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
#include <stdint.h>
#include <sys/stat.h>
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

struct point { const char *name; unsigned long pc; unsigned short original; unsigned int replacement; };
static const struct point points[] = {
    {"post_mul", 0x11e88, 0x83b3, 0},
    {"post_addi", 0x11e88, 0x83b3, 0x00160613},
    {"mul_stable_source", 0x11e88, 0x83b3, 0x02d50633}
};
static void snapshot(pid_t child, const char *dir, int sig) {
    siginfo_t info; memset(&info, 0, sizeof(info));
    if (ptrace(PTRACE_GETSIGINFO, child, 0, &info)) fail("siginfo");
    save(dir, "fault.siginfo", &info, sizeof(info));
    unsigned char regs[4096] = {0}; struct iovec iov = {regs, sizeof(regs)};
    if (ptrace(PTRACE_GETREGSET, child, NT_PRSTATUS, &iov)) fail("gpr");
    save(dir, "fault.gpr", regs, iov.iov_len);
    memset(regs, 0, sizeof(regs)); iov.iov_len = sizeof(regs); errno = 0;
    int vr = ptrace(PTRACE_GETREGSET, child, NT_RISCV_VECTOR, &iov), ve = errno;
    if (!vr) save(dir, "fault.vector", regs, iov.iov_len);
    char meta[160]; int n = snprintf(meta,sizeof(meta),
        "{\"signal\":%d,\"si_code\":%d,\"vector_errno\":%d,\"captured_before_delivery\":true}\n",
        sig, info.si_code, vr ? ve : 0);
    save(dir,"fault.meta.json",meta,n);
}
static int run_point(const struct point *point, const char *dir, char **command) {
    pid_t child = fork(); if (child < 0) fail("fork");
    if (!child) {
        if (ptrace(PTRACE_TRACEME,0,0,0)) fail("traceme");
        execvp(command[0],command); fail("exec");
    }
    int status;
    if (waitpid(child,&status,0)!=child || !WIFSTOPPED(status) || WSTOPSIG(status)!=SIGTRAP) fail("exec stop");
    if (ptrace(PTRACE_SETOPTIONS,child,0,PTRACE_O_EXITKILL)) fail("exitkill");
    /* Alter only the child's private text mapping, never the ELF file. */
    if (point->replacement) {
        errno=0; unsigned long old=ptrace(PTRACE_PEEKTEXT,child,(void *)0x11e80,0);
        if (errno || (old >> 32) != 0x02d60633) fail("unexpected original multiply");
        unsigned long changed=(old & 0xffffffffUL) | ((unsigned long)point->replacement << 32);
        if (ptrace(PTRACE_POKETEXT,child,(void *)0x11e80,(void *)changed)) fail("diagnostic instruction variant");
    }
    unsigned long aligned=point->pc & ~7UL, shift=(point->pc & 7UL)*8;
    errno=0; unsigned long word=ptrace(PTRACE_PEEKTEXT,child,(void *)aligned,0);
    if (errno || ((word >> shift) & 0xffff) != point->original) fail("unexpected frozen instruction");
    unsigned long patch=(word & ~(0xffffUL << shift)) | (0x9002UL << shift);
    if (ptrace(PTRACE_POKETEXT,child,(void *)aligned,(void *)patch)) fail("diagnostic private text patch");
    int deliver=0;
    for (;;) {
        if (ptrace(PTRACE_CONT,child,0,deliver)) fail("continue");
        if (waitpid(child,&status,0)!=child) fail("wait");
        if (WIFEXITED(status)) return 124;
        if (WIFSIGNALED(status)) return WTERMSIG(status);
        if (!WIFSTOPPED(status)) return 125;
        deliver=WSTOPSIG(status);
        if (deliver==SIGTRAP || deliver==SIGSEGV || deliver==SIGILL || deliver==SIGBUS) {
            snapshot(child,dir,deliver);
            unsigned long regs[32]={0};struct iovec v={regs,sizeof(regs)};
            if (ptrace(PTRACE_GETREGSET,child,NT_PRSTATUS,&v)) fail("checkpoint pc");
            int matched=deliver==SIGTRAP && regs[0]==point->pc;
            if (ptrace(PTRACE_KILL,child,0,0)) fail("stop diagnostic child");
            if (waitpid(child,&status,0)!=child) fail("reap diagnostic child");
            return matched ? 0 : 123;
        }
    }
}
int main(int argc,char **argv) {
    if (argc<3) return 125;
    int failures=0;
    for (size_t i=0;i<sizeof(points)/sizeof(points[0]);i++) {
        char dir[4096]; if(snprintf(dir,sizeof(dir),"%s/%s",argv[1],points[i].name)>=(int)sizeof(dir)) return 125;
        if (mkdir(dir,0700)) fail("checkpoint directory");
        int rc=run_point(&points[i],dir,argv+2);
        char value[20];int n=snprintf(value,sizeof(value),"%d\n",rc);save(dir,"capture.status",value,n);
        failures += rc != 0;
    }
    return failures ? 123 : 0;
}
