#!/usr/bin/env bash
# Feed a boom.md DFA through GCC 15.1's own md generators (genattrtab, which
# also runs the DFA/automaton generator, and genautomata) using a private copy
# of gcc/config/riscv/*.md.  The GCC source and build trees are only read.
# usage: check_dfa.sh <boom.md> <outdir>
set -euo pipefail
MD="$(readlink -f "$1")"; OUT="$(readlink -f "$2")"
SRC=/home/eecs/trazzaque/spec2017-research/compiler-loop/source/gcc
BLD=/home/eecs/trazzaque/spec2017-research/compiler-loop/build/gcc
rm -rf "$OUT"; mkdir -p "$OUT/config/riscv"
cp "$SRC"/common.md "$OUT/"
cp "$SRC"/config/riscv/*.md "$OUT/config/riscv/"
cp "$MD" "$OUT/config/riscv/boom.md"
python3 - "$OUT/config/riscv/riscv.md" <<'EOF'
import re, sys
p = sys.argv[1]; s = open(p).read()
old = '"generic,sifive_7,sifive_p400,sifive_p600,xiangshan,generic_ooo"'
assert s.count(old) == 1, "pinned riscv.md tune attr shape differs"
s = s.replace(old, old[:-1] + ',boom"')
s += '\n(include "boom.md")\n'
open(p, "w").write(s)
EOF
cd "$OUT"
"$BLD"/build/genattrtab common.md config/riscv/riscv.md "$BLD"/insn-conditions.md \
   -Atmp-attrtab.cc -Dtmp-dfatab.cc -Ltmp-latencytab.cc > genattrtab.log 2>&1
"$BLD"/build/genautomata common.md config/riscv/riscv.md "$BLD"/insn-conditions.md \
   > tmp-automata.cc 2> genautomata.log
grep -c "boom" tmp-dfatab.cc > boom_mentions.txt || true
# insn_default_latency / dfa tables mention our reservations
grep -o "boom_[a-z_0-9]*" tmp-dfatab.cc tmp-latencytab.cc | sort | uniq -c | sort -rn | head -40 > boom_symbols.txt || true
echo "genattrtab+genautomata OK: $(wc -c < tmp-dfatab.cc) bytes dfatab, $(wc -c < tmp-automata.cc) bytes automata"
