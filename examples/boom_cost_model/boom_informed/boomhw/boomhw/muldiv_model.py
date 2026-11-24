"""Bit-accurate Python transliteration of rocket-chip MulDiv (divide path).

Source: generators/rocket-chip/src/main/scala/rocket/Multiplier.scala
(rocket-chip 55bcad0f, as instantiated by BOOM v3 DivUnit,
generators/boom/src/main/scala/v3/exu/execution-units/functional-unit.scala:682).

`simulate()` steps the same state machine as the Chisel (s_ready ->
[s_neg_inputs] -> s_div x N -> [s_neg_output] -> s_done_div) and returns the
response data and the number of cycles from the req.fire cycle to the first
resp.valid cycle.  `closed_form_cycles()` is the derived analytic formula.
Both are checked against Verilator runs of the elaborated MegaBOOM MulDiv
(rtl_unit_sim/results/muldiv_results.csv) by tests/test_muldiv_model.py.

Only the divide functions are modelled: in BOOM all multiplies go to the
separate PipelinedMultiplier (FU_MUL), never to MulDiv.
"""
from dataclasses import dataclass

FN_DIV, FN_DIVU, FN_REM, FN_REMU = 4, 5, 6, 7
DW_32, DW_64 = 0, 1


@dataclass(frozen=True)
class MulDivParams:
    mulUnroll: int = 1
    divUnroll: int = 1
    mulEarlyOut: bool = False
    divEarlyOut: bool = False
    divEarlyOutGranularity: int = 1


def _log2_floor(x):
    """chisel3.util.Log2 (returns 0 for x == 0)."""
    return x.bit_length() - 1 if x > 0 else 0


def _log2_ceil(x):
    return (x - 1).bit_length()


def simulate(fn, dw, in1, in2, cfg=MulDivParams(divEarlyOut=True), w=64):
    """Return (data, cycles_fire_to_resp_valid, trace)."""
    assert cfg.divUnroll >= 1
    M = lambda n: (1 << n) - 1
    cmd_hi = fn in (FN_REM, FN_REMU)
    lhs_signed = rhs_signed = fn in (FN_DIV, FN_REM)
    half = (w > 32) and dw == DW_32

    def sext(x, signed):
        x &= M(w)
        sign = bool(signed) and bool((x >> (w // 2 - 1)) & 1 if half else (x >> (w - 1)) & 1)
        if half:
            hi = M(w // 2) if sign else 0
        else:
            hi = x >> (w // 2)
        return (hi << (w // 2)) | (x & M(w // 2)), sign

    lhs_in, lhs_sign = sext(in1, lhs_signed)
    rhs_in, rhs_sign = sext(in2, rhs_signed)

    # registers after the req.fire edge
    state = "neg_inputs" if (lhs_sign or rhs_sign) else "div"
    is_hi = cmd_hi
    res_hi = False
    count = 0
    count_bits = _log2_ceil(w // cfg.divUnroll + 1)
    neg_out = lhs_sign if cmd_hi else (lhs_sign != rhs_sign)
    divisor = ((1 if rhs_sign else 0) << w) | rhs_in          # w+1 bits
    remainder = lhs_in                                        # 2w+2 bits (div uses 2w+1)
    trace = [state]
    cycles = 1  # we are now in the cycle after fire
    while state != "done_div":
        subtractor = ((remainder >> w) & M(w + 1)) - divisor
        subtractor &= M(w + 1)
        result = (remainder >> (w + 1)) & M(w) if res_hi else remainder & M(w)
        negated_remainder = (-result) & M(w)
        if state == "neg_inputs":
            if (remainder >> (w - 1)) & 1:
                remainder = negated_remainder
            if (divisor >> (w - 1)) & 1:
                divisor = subtractor
            state = "div"
        elif state == "neg_output":
            remainder = negated_remainder
            state = "done_div"
            res_hi = False
        elif state == "div":
            rem = remainder
            unrolls = []
            for i in range(cfg.divUnroll):
                if i == 0:
                    difference = subtractor
                else:
                    difference = (((rem >> w) & M(w + 1)) - (divisor & M(w))) & M(w + 1)
                less = (difference >> w) & 1
                upper = ((rem >> w) & M(w)) if less else (difference & M(w))
                rem = (upper << (w + 1)) | ((rem & M(w)) << 1) | (0 if less else 1)
                unrolls.append(rem)
            new_remainder = unrolls[-1]
            new_state, new_res_hi = state, res_hi
            if count == w // cfg.divUnroll:
                new_state = "neg_output" if neg_out else "done_div"
                new_res_hi = is_hi
                if w % cfg.divUnroll < cfg.divUnroll - 1:
                    new_remainder = unrolls[w % cfg.divUnroll]
            new_count = (count + 1) & M(count_bits)
            divby0 = count == 0 and not ((subtractor >> w) & 1)
            if cfg.divEarlyOut:
                lw = _log2_ceil(w)
                align = 1 << _log2_floor(max(cfg.divUnroll, cfg.divEarlyOutGranularity))
                align_mask = (~(align - 1)) & M(lw)
                divisor_msb = _log2_floor(divisor & M(w)) & align_mask
                dividend_msb = _log2_floor(remainder & M(w)) | ((~align_mask) & M(lw))
                e_out_pos = (~((dividend_msb - divisor_msb) & M(lw))) & M(lw)
                e_out = count == 0 and not divby0 and e_out_pos >= align
                if e_out:
                    new_remainder = ((remainder & M(w)) << e_out_pos) & M(2 * w + 2)
                    new_count = e_out_pos >> _log2_floor(cfg.divUnroll)
            if divby0 and not is_hi:
                neg_out = False
            remainder, state, res_hi, count = new_remainder, new_state, new_res_hi, new_count
        trace.append(state)
        cycles += 1
    result = (remainder >> (w + 1)) & M(w) if res_hi else remainder & M(w)
    lo = result & M(w // 2)
    hi = (M(w // 2) if (lo >> (w // 2 - 1)) & 1 else 0) if half else (result >> (w // 2))
    return (hi << (w // 2)) | lo, cycles, trace


def operand_magnitudes(fn, dw, in1, in2, w=64):
    """Magnitudes the divider actually sees after sign handling."""
    signed = fn in (FN_DIV, FN_REM)
    bits = 32 if dw == DW_32 else w

    def mag(x):
        x &= (1 << bits) - 1
        neg = signed and (x >> (bits - 1)) & 1
        if neg:
            x = (1 << bits) - x
        return x, bool(neg)

    a, an = mag(in1)
    b, bn = mag(in2)
    return a, an, b, bn


def closed_form_cycles(fn, dw, in1, in2, cfg=MulDivParams(divEarlyOut=True), w=64):
    """Analytic fire->resp.valid cycle count (divUnroll=1, granularity 1).

    L = 1 + neg_in + N + neg_out, with
      neg_in  = 1 if a signed op has a negative operand
      neg_out = 1 if the (non-div-by-zero) result must be negated
                (div: sign(a) != sign(b); rem: sign(a)); for divide-by-zero
                neg_out is cleared for div (not rem).
      d = floor(log2 |a|) (0 if a == 0), v = floor(log2 |b|)
      eOutPos = (63 - ((d - v) mod 64))  (6-bit wrap)
      N = 65                if b == 0, or not earlyOut, or eOutPos == 0
        = 66 - eOutPos      otherwise
    i.e. for |a| >= |b| in MSB terms N = 3 + (d - v); when MSB(a) < MSB(b)
    (quotient 0) the 6-bit subtraction wraps and N = 67 - (v - d) (slow!).
    """
    assert cfg.divUnroll == 1 and cfg.divEarlyOutGranularity == 1 and w == 64
    a, an, b, bn = operand_magnitudes(fn, dw, in1, in2, w)
    cmd_hi = fn in (FN_REM, FN_REMU)
    neg_in = 1 if (an or bn) else 0
    if b == 0:
        n = 65
        neg_out = 1 if (cmd_hi and an) else 0
    else:
        d = _log2_floor(a)
        v = _log2_floor(b)
        e_out_pos = 63 - ((d - v) % 64)
        n = 65 if (not cfg.divEarlyOut or e_out_pos < 1) else 66 - e_out_pos
        neg_out = 1 if ((an if cmd_hi else (an != bn))) else 0
    return 1 + neg_in + n + neg_out


def reference(fn, dw, a, b):
    """RISC-V M semantics (for checking the model)."""
    M64 = (1 << 64) - 1

    def s(x, bits):
        x &= (1 << bits) - 1
        return x - (1 << bits) if x >> (bits - 1) else x

    bits = 64 if dw == DW_64 else 32
    ua, ub = a & ((1 << bits) - 1), b & ((1 << bits) - 1)
    sa, sb = s(a, bits), s(b, bits)
    if fn == FN_DIVU:
        r = ((1 << bits) - 1) if ub == 0 else ua // ub
    elif fn == FN_REMU:
        r = ua if ub == 0 else ua % ub
    elif fn == FN_DIV:
        if sb == 0:
            r = -1
        elif sa == -(1 << (bits - 1)) and sb == -1:
            r = sa
        else:
            q = abs(sa) // abs(sb)
            r = q if (sa < 0) == (sb < 0) else -q
    else:  # REM
        if sb == 0:
            r = sa
        elif sa == -(1 << (bits - 1)) and sb == -1:
            r = 0
        else:
            m = abs(sa) % abs(sb)
            r = m if sa >= 0 else -m
    r &= (1 << bits) - 1
    if bits == 32:
        r = s(r, 32)
    return r & M64
