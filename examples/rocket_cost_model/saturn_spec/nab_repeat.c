/* Diagnostic launcher for unchanged SPEC payloads; never a performance run. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/personality.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void fail(const char *name) { perror(name); exit(125); }

static int create(const char *directory, const char *name) {
    char path[PATH_MAX];
    if (snprintf(path, sizeof(path), "%s/%s", directory, name) >= (int)sizeof(path)) {
        errno = ENAMETOOLONG; fail("diagnostic path");
    }
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) fail("exclusive diagnostic output");
    return fd;
}

static void maps(pid_t child, const char *directory) {
    char path[64], buffer[4096];
    snprintf(path, sizeof(path), "/proc/%ld/maps", (long)child);
    int in = open(path, O_RDONLY), out = create(directory, "exec-maps.txt");
    if (in < 0) fail("read child mappings");
    ssize_t n;
    while ((n = read(in, buffer, sizeof(buffer))) > 0) {
        ssize_t done = 0;
        while (done < n) {
            ssize_t written = write(out, buffer + done, n - done);
            if (written <= 0) fail("write child mappings");
            done += written;
        }
    }
    if (n < 0 || close(in) || close(out)) fail("finish child mappings");
}

int main(int argc, char **argv) {
    if (argc < 3) return 125;
    char executable[PATH_MAX];
    if (!realpath(argv[2], executable)) fail("resolve unchanged executable");
    const char *modes = getenv("SATURN_NAB_DIAGNOSTIC_MODES");
    if (!modes) modes = "normal,normal";
    if (strlen(modes) >= 128) return 125;
    char list[128]; strcpy(list, modes);
    char *selected[8], *save = NULL;
    unsigned count = 0;
    for (char *m = strtok_r(list, ",", &save); m; m = strtok_r(NULL, ",", &save)) {
        if (count == 8 || (strcmp(m, "normal") && strcmp(m, "no-aslr") && strcmp(m, "fifo")))
            return 125;
        selected[count++] = m;
    }
    if (!count) return 125;
    char root[PATH_MAX];
    if (snprintf(root, sizeof(root), "%s/repetitions", argv[1]) >= (int)sizeof(root)) return 125;
    if (mkdir(root, 0700)) fail("exclusive repetitions directory");
    int failed = 0;
    for (unsigned i = 0; i < count; ++i) {
        char dir[PATH_MAX];
        if (snprintf(dir, sizeof(dir), "%s/%u-%s", root, i, selected[i]) >= (int)sizeof(dir)) return 125;
        if (mkdir(dir, 0700)) fail("exclusive repetition");
        pid_t copier = fork();
        if (copier < 0) fail("fork input copy");
        if (!copier) {
            execl("/bin/cp", "cp", "-R", "hkrdenq", dir, (char *)NULL);
            fail("copy unchanged NAB inputs");
        }
        int copied;
        if (waitpid(copier, &copied, 0) != copier || !WIFEXITED(copied) || WEXITSTATUS(copied))
            fail("copy unchanged NAB inputs");
        fflush(NULL);
        pid_t child = fork();
        if (child < 0) fail("fork workload");
        if (!child) {
            int out = create(dir, "stdout.txt"), err = create(dir, "stderr.txt");
            if (dup2(out, STDOUT_FILENO) < 0 || dup2(err, STDERR_FILENO) < 0) fail("redirect workload");
            close(out); close(err);
            if (chdir(dir)) fail("isolated diagnostic working directory");
            if (!strcmp(selected[i], "no-aslr")) {
                int current = personality(0xffffffffUL);
                if (current < 0 || personality((unsigned long)current | ADDR_NO_RANDOMIZE) < 0)
                    fail("disable ASLR for diagnostic child");
            }
            if (!strcmp(selected[i], "fifo")) {
                struct sched_param param = {.sched_priority = 1};
                if (sched_setscheduler(0, SCHED_FIFO, &param)) fail("diagnostic FIFO scheduling");
            }
            if (ptrace(PTRACE_TRACEME, 0, NULL, NULL)) fail("trace exec");
            execv(executable, argv + 2); fail("exec unchanged workload");
        }
        int status;
        if (waitpid(child, &status, 0) != child) fail("wait for exec");
        int exec_seen = WIFSTOPPED(status) && WSTOPSIG(status) == SIGTRAP;
        if (exec_seen) {
            maps(child, dir);
            if (ptrace(PTRACE_DETACH, child, NULL, NULL)) fail("detach workload");
            if (waitpid(child, &status, 0) != child) fail("wait for workload");
        }
        int code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + (WIFSIGNALED(status) ? WTERMSIG(status) : 0);
        FILE *receipt = fdopen(create(dir, "status.json"), "w");
        if (!receipt) fail("open diagnostic receipt");
        fprintf(receipt, "{\"diagnostic_only\":true,\"mode\":\"%s\",\"exec_seen\":%s,\"exit_code\":%d}\n",
                selected[i], exec_seen ? "true" : "false", code);
        if (fclose(receipt)) fail("finish diagnostic receipt");
        printf("NAB_DIAGNOSTIC_REPEAT=%u MODE=%s EXIT=%d EXEC=%d\n", i, selected[i], code, exec_seen);
        fflush(stdout);
        failed |= !exec_seen || code != 0;
    }
    return failed ? 1 : 0;
}
