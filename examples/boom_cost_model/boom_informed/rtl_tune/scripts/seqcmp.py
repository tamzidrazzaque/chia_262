import sys, glob, os, collections, hashlib
sys.path.insert(0, "/scratch/trazzaque/SLICE/boom-research/rtl-tune/scripts")
from asmfuncs import disasm
objdump, x, y = sys.argv[1], sys.argv[2], sys.argv[3]
def load(d):
    per = {}
    for o in sorted(glob.glob(os.path.join(d, "**", "*.o"), recursive=True)):
        rel = os.path.relpath(o, d)
        for f, ins in disasm(objdump, o).items(): per[(rel, f)] = ins
    return per
X, Y = load(x), load(y)
c = collections.Counter()
for k in set(X) & set(Y):
    a, b = X[k], Y[k]
    if a == b: c["identical"] += 1
    elif [i[0] for i in a] == [i[0] for i in b]: c["same_opcode_sequence_regs_differ"] += 1
    elif sorted(i[0] for i in a) == sorted(i[0] for i in b): c["truly_reordered"] += 1
    else: c["different_opcodes"] += 1
print(dict(c))
