"""Minimal Scala source access with file:line provenance.

Not a Scala parser: just enough structure (balanced-paren call extraction,
named-argument splitting, case-class default parsing, anchored regex lookup)
to pull Chisel generator parameters out of BOOM / rocket-chip / chipyard
sources.  Every value returned carries 'generators/<repo>/...:<line>'.
"""
import os
import re
import subprocess
import tarfile
import io


class SourceError(RuntimeError):
    pass


class Prov(dict):
    """A value with provenance: {'value', 'src', 'origin', 'expr'}."""

    @property
    def v(self):
        return self["value"]


def literal(expr):
    """Evaluate a simple Scala literal / expression used in configs."""
    e = expr.strip()
    if e in ("true", "false"):
        return e == "true"
    m = re.fullmatch(r"Some\((.*)\)", e, re.S)
    if m:
        return literal(m.group(1))
    if re.fullmatch(r"-?\d+", e):
        return int(e)
    if re.fullmatch(r"[\d\s\*\+\-\(\)]+", e):           # e.g. 4*4
        return int(eval(e, {"__builtins__": {}}))       # digits/operators only
    m = re.fullmatch(r"(IQT_\w+)\.litValue", e)
    if m:
        return m.group(1)
    m = re.fullmatch(r"BigInt\((\d+)\)", e)
    if m:
        return int(m.group(1))
    return e                                             # keep as expression text


class SourceTree:
    """Files laid out as in the chipyard image: <root>/<repo>/src/main/scala/..."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._cache = {}

    def rel(self, path):
        return "generators/" + path

    def text(self, path):
        if path not in self._cache:
            full = os.path.join(self.root, path)
            if not os.path.exists(full):
                raise SourceError(f"missing source {path} under {self.root}")
            with open(full, encoding="utf-8") as f:
                self._cache[path] = f.read()
        return self._cache[path]

    def line_of(self, path, offset):
        return self.text(path).count("\n", 0, offset) + 1

    def where(self, path, offset):
        return f"{self.rel(path)}:{self.line_of(path, offset)}"

    def anchor(self, path, pattern, flags=0, group=0):
        """Find a required pattern; return (match, 'file:line'). Fails loudly."""
        m = re.search(pattern, self.text(path), flags)
        if not m:
            raise SourceError(f"anchor not found in {path}: {pattern!r}")
        return m, self.where(path, m.start(group))

    def anchors(self, path, pattern, flags=0):
        return [(m, self.where(path, m.start())) for m in re.finditer(pattern, self.text(path), flags)]

    # ---- structural helpers -------------------------------------------------
    def balanced(self, path, open_idx):
        """Return index just past the paren that closes text[open_idx] == '('."""
        t = self.text(path)
        assert t[open_idx] == "("
        depth, i, in_str = 0, open_idx, False
        while i < len(t):
            c = t[i]
            if in_str:
                if c == '"' and t[i - 1] != "\\":
                    in_str = False
            elif c == '"':
                in_str = True
            elif t.startswith("//", i):
                i = t.index("\n", i)
                continue
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise SourceError(f"unbalanced parens in {path} at {open_idx}")

    def block(self, path, start_pattern):
        """(start, end) span of the first balanced '( ... )' after a pattern."""
        m, _ = self.anchor(path, start_pattern)
        open_idx = self.text(path).index("(", m.end() - 1)
        return open_idx, self.balanced(path, open_idx)

    def split_args(self, path, open_idx, close_idx):
        """Top-level comma split of text[open_idx+1:close_idx-1] -> [(arg, offset)]."""
        t = self.text(path)
        out, depth, start, i, in_str = [], 0, open_idx + 1, open_idx + 1, False
        end = close_idx - 1
        while i < end:
            c = t[i]
            if in_str:
                if c == '"' and t[i - 1] != "\\":
                    in_str = False
            elif c == '"':
                in_str = True
            elif t.startswith("//", i):
                nl = t.index("\n", i)
                i = nl
                continue
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == "," and depth == 0:
                out.append((t[start:i], start))
                start = i + 1
            i += 1
        if t[start:end].strip():
            out.append((t[start:end], start))
        cleaned = []
        for arg, off in out:
            # strip comments and leading whitespace but keep offset of first token
            no_comments = re.sub(r"//[^\n]*", "", arg)
            no_comments = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), no_comments, flags=re.S)
            lead = len(no_comments) - len(no_comments.lstrip())
            cleaned.append((no_comments.strip(), off + lead))
        return [(a, o) for a, o in cleaned if a]

    def named_call_args(self, path, open_idx, close_idx):
        """Parse `Name(k = v, k2 = v2)` style args -> {k: Prov}."""
        res = {}
        for arg, off in self.split_args(path, open_idx, close_idx):
            m = re.match(r"(\w+)\s*=(?!=)\s*(.*)", arg, re.S)
            if not m:
                continue
            res[m.group(1)] = Prov(value=literal(m.group(2)), expr=m.group(2).strip(),
                                   src=self.where(path, off), origin="config")
        return res

    def find_call_in(self, path, name, lo, hi):
        """First `name(` call inside [lo, hi) -> (open_idx, close_idx) or None."""
        t = self.text(path)
        m = re.compile(r"\b" + re.escape(name) + r"\s*\(").search(t, lo, hi)
        if not m:
            return None
        o = m.end() - 1
        return o, self.balanced(path, o)

    def find_calls_in(self, path, name, lo, hi):
        t = self.text(path)
        res, pos = [], lo
        rx = re.compile(r"\b" + re.escape(name) + r"\s*\(")
        while True:
            m = rx.search(t, pos, hi)
            if not m:
                return res
            o = m.end() - 1
            c = self.balanced(path, o)
            res.append((o, c))
            pos = c

    def case_class_defaults(self, path, cls):
        """`case class X(a: Int = 1, ...)` -> {a: Prov(default)}."""
        o, c = self.block(path, r"case class " + re.escape(cls) + r"\s*\(")
        res = {}
        for arg, off in self.split_args(path, o, c):
            m = re.match(r"(?:val\s+)?(\w+)\s*:\s*([^=]+?)\s*=\s*(.*)", arg, re.S)
            if m:
                res[m.group(1)] = Prov(value=literal(m.group(3)), expr=m.group(3).strip(),
                                       src=self.where(path, off), origin="default",
                                       type=m.group(2).strip())
        return res


def snapshot_from_docker(image, dest, paths, chipyard="/home/ray/chipyard"):
    """Copy source subtrees out of a read-only docker image via a tar stream.

    Uses `docker run --rm` only (never commit/tag/rm the image).
    """
    os.makedirs(dest, exist_ok=True)
    cmd = ["docker", "run", "--rm", "--entrypoint", "bash", image, "-c",
           f"unset LD_PRELOAD; cd {chipyard}/generators && tar cf - " + " ".join(paths)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if not proc.stdout:
        raise SourceError("docker snapshot produced no data")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tf:
        for member in tf.getmembers():
            if member.name.startswith("/") or ".." in member.name.split("/"):
                raise SourceError(f"unsafe tar member {member.name}")
        tf.extractall(dest)
    return dest
