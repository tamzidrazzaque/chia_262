"""Small empirical surrogate with measured labels and an explicit cold start.

Inverse-distance regression predicts log speedup from bounded tuning settings.
Leave-one-executable-group-out pair ranking must beat 60% before exploitation.
This model is deliberately dependency-free and does not claim SPEC transfer.
"""

import math
import statistics
import re

from chia.chipyard.cost_model import BASE_COSTS, validate_costs, validate_scheduling


def features(proposal):
    costs = validate_costs(proposal["costs"])
    issue = proposal.get("scheduling", {"issue_rate": 4 if proposal.get("tuning") == "boom" else 1})
    validate_scheduling(issue)
    return tuple(float(x) for key in BASE_COSTS for x in
                 (costs[key] if isinstance(costs[key], list) else [costs[key]])) + (
                     float(issue["issue_rate"]), float(proposal.get("tuning", "rocket") == "boom"))


def distance(a, b):
    return math.sqrt(sum(((x - y) / max(abs(x), abs(y), 1)) ** 2 for x, y in zip(a, b)))


def predict(proposal, observations):
    target = features(proposal)
    nearest = sorted((distance(target, features(o["proposal"])), math.log(o["speedup"])) for o in observations)[:3]
    if not nearest:
        return {"log_speedup": 0.0, "uncertainty": 1.0}
    if nearest[0][0] == 0:
        return {"log_speedup": nearest[0][1], "uncertainty": 0.0}
    weights = [1 / max(d, 0.01) ** 2 for d, _ in nearest]
    mean = sum(w * value for w, (_, value) in zip(weights, nearest)) / sum(weights)
    spread = statistics.pstdev(value for _, value in nearest)
    return {"log_speedup": mean, "uncertainty": spread + nearest[0][0] * 0.01}


def validate_observations(observations):
    seen, target = set(), None
    for o in observations:
        if not o.get("correct") or not o.get("FPGA_executed") or not o.get("target_id"):
            raise ValueError("surrogate labels require correct hardware measurements and target identity")
        if not re.fullmatch(r"[0-9a-f]{64}", o.get("executable_sha256", "")):
            raise ValueError("labels require generated executable identity")
        if not isinstance(o["speedup"], (int, float)) or not math.isfinite(o["speedup"]) or o["speedup"] <= 0:
            raise ValueError("invalid hardware speedup")
        if target is not None and target != o["target_id"]:
            raise ValueError("cannot mix hardware/runtime identities")
        target = o["target_id"]
        key = features(o["proposal"])
        if key in seen:
            raise ValueError("aggregate repeated measurements before fitting")
        seen.add(key)


def validation_report(observations):
    validate_observations(observations)
    groups = {o["executable_sha256"] for o in observations}
    counts = {"unique_configurations": len(observations), "unique_executables": len(groups)}
    if len(groups) < 8:
        return {"ready": False, **counts, "reason": "need at least 8 distinct measured executables; identical code is one group"}
    predictions = [predict(o["proposal"], [other for other in observations
                    if other["executable_sha256"] != o["executable_sha256"]])["log_speedup"] for o in observations]
    good = total = 0
    for i, a in enumerate(observations):
        for j in range(i):
            actual = math.log(a["speedup"]) - math.log(observations[j]["speedup"])
            if abs(actual) < 1e-5:
                continue
            total += 1
            good += actual * (predictions[i] - predictions[j]) > 0
    accuracy = good / total if total else 0.0
    return {"ready": accuracy > 0.6, **counts,
            "leave_one_executable_group_out_pair_accuracy": accuracy,
            "interpretation": "Internal proxy validation only; no SPEC generalization claim"}


def suggest(pool, observations, step=0):
    report = validation_report(observations)
    tested = {features(o["proposal"]) for o in observations}
    remaining = [p for p in pool if features(p) not in tested]
    if not remaining:
        raise ValueError("proposal pool exhausted")
    if not report["ready"] or step % 4 == 0:
        selected = max(remaining, key=lambda p: min(
            (distance(features(p), features(o["proposal"])) for o in observations), default=1.0))
        strategy = "diversity exploration"
    else:
        selected = max(remaining, key=lambda p: sum(predict(p, observations).values()))
        strategy = "predicted log speedup plus uncertainty"
    return {"proposal": selected, "strategy": strategy, "validation": report,
            "prediction": predict(selected, observations)}
