#!/usr/bin/env python3
"""Separate environment from predictor, then test held-out.

Environment (fixed, never selected): schedule, length, noise. Drawn from env seeds.
Predictor (what is selected): stable_hits in BOUNDS (2..4). Baseline = 3.
Selection uses SEL envs only. Held-out uses HELD envs only (disjoint).

Pre-registered success criterion (fixed before running):
  mean(held-out chosen - baseline) > 0  AND  chosen better on > half of held-out envs.
"""
import json, random, statistics
import natural_lab as nl

SEL_MASTER, HELD_MASTER = 1111, 2222
N_SEL, N_HELD, BASELINE = 20, 30, 3
CANDIDATES = list(range(nl.BOUNDS["stable_hits"][0], nl.BOUNDS["stable_hits"][1] + 1))


def envs(master, n):
    rng = random.Random(master)
    return [rng.randrange(2**31) for _ in range(n)]


def accuracy(env_seed, stable_hits):
    env = nl.draw_params(random.Random(env_seed))   # environment only
    env.pop("stable_hits", None)
    obs_rng = random.Random(env_seed + 1)
    pred = nl.Predictor(stable_hits)
    preds = [pred.observe(dict(nl.make_observation(obs_rng, env, i)))
             for i in range(env["length"])]
    ev = [p for p in preds if p["detected"] is not None]
    return sum(p["detected"] == nl.regime_at(env, p["index"]) for p in ev) / len(ev)


sel = envs(SEL_MASTER, N_SEL)
sel_mean = {h: statistics.mean(accuracy(e, h) for e in sel) for h in CANDIDATES}
chosen = max(sel_mean, key=sel_mean.get)

held = envs(HELD_MASTER, N_HELD)
assert not set(held) & set(sel)
diffs = [accuracy(e, chosen) - accuracy(e, BASELINE) for e in held]
better = sum(d > 0 for d in diffs)
mean_diff = statistics.mean(diffs)
passed = mean_diff > 0 and better > N_HELD / 2

print(json.dumps({
    "selection_means": {h: round(v, 4) for h, v in sel_mean.items()},
    "chosen_stable_hits": chosen, "baseline_stable_hits": BASELINE,
    "held_out_mean_diff": round(mean_diff, 4),
    "sd_diff": round(statistics.stdev(diffs), 4),
    "chosen_better_on": better, "of": N_HELD,
    "criterion_passed": passed,
}, indent=2))
