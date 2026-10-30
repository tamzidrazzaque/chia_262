"""Source-level gates for the separate experimental BOOM tune entry."""

import pytest

from chia.chipyard.boom_model import SEED_COSTS, render_sources, scheduling_description
from chia.chipyard.test.test_cost_model_loop import table


def originals():
    return {"riscv.cc": table() + "/* A table describing all the processors GCC knows about.  */\n",
            "riscv-cores.def": 'RISCV_TUNE("rocket", generic, rocket_tune_info)\n#undef RISCV_TUNE\n',
            "riscv-opts.h": "enum x {\n  generic,\n  sifive_7\n};\n",
            "riscv.md": '(define_attr "tune" "generic,sifive_7")\n'}


def test_boom_is_separate_and_preserves_original_rocket():
    source = originals()
    changed = render_sources(source, SEED_COSTS)
    assert source["riscv.cc"].split("after")[0] in changed["riscv.cc"]
    assert "boom_tune_info" in changed["riscv.cc"]
    assert "4, /* issue_rate */" in changed["riscv.cc"]
    assert 'RISCV_TUNE("boom", boom, boom_tune_info)' in changed["riscv-cores.def"]
    assert '"generic,sifive_7,boom"' in changed["riscv.md"]
    assert '(include "boom.md")' in changed["riscv.md"]
    assert "sifive_7,\n  boom" in changed["riscv-opts.h"]


def test_changed_source_and_unbounded_issue_rate_rejected():
    source = originals()
    source["riscv.md"] = "unexpected compiler revision"
    with pytest.raises(ValueError):
        render_sources(source, SEED_COSTS)
    with pytest.raises(ValueError):
        render_sources(originals(), SEED_COSTS, 100)


def test_pipelined_multiply_is_not_blocked_for_ten_cycles():
    text = scheduling_description()
    assert '"boom_imul" 3' in text
    assert "boom_mul*" not in text
    assert '"boom_fp" 4' in text
    assert '"boom_idiv_di" 66' in text
    assert 'eq_attr "tune" "generic"' not in text
