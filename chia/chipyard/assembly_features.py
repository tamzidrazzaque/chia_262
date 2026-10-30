"""Explanatory opcode counts from GCC RISC-V assembly, without runtime claims."""

from collections import Counter
import re


def extract(text):
    functions = {}
    current = None
    for line in text.splitlines():
        label = re.fullmatch(r"([A-Za-z_][\w.$]*):", line.strip())
        if label:
            current = label[1]
            functions.setdefault(current, Counter())
            continue
        if re.match(r"\s*\.size\s+", line):
            current = None
        instruction = re.match(r"\s+([a-z][a-z0-9.]*)\s*(?:\s|$)", line)
        if current and instruction:
            functions[current][instruction[1]] += 1
    categories = {
        "integer_multiply": {"mul", "mulw", "mulh", "mulhu", "mulhsu"},
        "integer_divide": {"div", "divu", "divw", "divuw", "rem", "remu", "remw", "remuw"},
        "load": {"ld", "lw", "lwu", "lh", "lhu", "lb", "lbu", "fld", "flw"},
        "store": {"sd", "sw", "sh", "sb", "fsd", "fsw"},
        "conditional_branch": {"beq", "bne", "blt", "bge", "bltu", "bgeu", "beqz", "bnez", "ble", "bgt"},
    }
    return {name: {"opcode_counts": dict(counts), "static_instructions": sum(counts.values()),
                   **{category: sum(counts[op] for op in ops) for category, ops in categories.items()},
                   "fp_register_moves": sum(count for op, count in counts.items() if op.startswith("fmv."))}
            for name, counts in functions.items()}
