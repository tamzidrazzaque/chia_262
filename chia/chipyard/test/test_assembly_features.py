from chia.chipyard.assembly_features import extract


def test_instruction_counts_ignore_labels_and_directives():
    text = 'multiply:\n\t.cfi_startproc\n.L10:\n\tmul a0,a1,a2\n\tld a1,0(a3)\n\tbne a0,a1,.L10\n\tret\n\t.size multiply, .-multiply\n'
    data = extract(text)
    assert set(data) == {"multiply"}
    assert data["multiply"]["static_instructions"] == 4
    assert data["multiply"]["integer_multiply"] == 1
    assert data["multiply"]["load"] == 1
    assert data["multiply"]["conditional_branch"] == 1
