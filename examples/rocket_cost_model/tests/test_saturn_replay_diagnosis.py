from examples.rocket_cost_model.saturn_spec.replay_diagnosis import classify, multiplication_count


def points():
    common = dict(pc=0x11e88, a0=0x144, a3=4, a4=0xf1924, t2=9,
                  s0=0xf1910, s1=0x144, s5=5, vl=4, vtype=0x17, vstart=0)
    return {k: {'valid': True, 'registers': {**common, 'a2': value}} for k, value in
            [('post_mul', 0x5100), ('post_addi', 0x145), ('mul_stable_source', 0x510)]}


def test_discriminating_controls():
    data = points()
    assert multiplication_count(0x144, 4, 0x5100) == 3
    assert classify(data)['outcome'] == 'iterative_mul_replay_side_effect_pattern'
    data['post_mul']['registers']['a2'] = 0x510
    assert classify(data)['outcome'] == 'not_reproduced'
    data['post_mul']['registers']['a2'] = 0x5100
    data['post_addi']['registers']['a2'] = 0x147
    assert classify(data)['outcome'] == 'scalar_operand_or_generic_replay_unresolved'


def test_incomplete_and_unmatched_are_not_diagnoses():
    data = points()
    data['mul_stable_source'] = {'valid': False, 'capture_status': '11'}
    assert classify(data)['outcome'] == 'incomplete_controls'
    data = points()
    data['post_mul']['registers']['vl'] = 1
    assert classify(data)['outcome'] == 'unmatched_control_context'
    assert multiplication_count(324, 4, 325) is None
