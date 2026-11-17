#!/usr/bin/env python3
"""Branching simulation from a verified base record. Standard library only.

Reuses the natural-lab mechanics (same draw, observation, predictor) so each
child is evaluated the same way as the base. Every child gets a deterministic
seed derived from its parent, so the whole tree replays exactly.
"""
import hashlib, json, random, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for folder in (HERE, Path.home() / "natural-lab-src"):
    if (folder / "natural_lab.py").is_file():
        sys.path.insert(0, str(folder))
        break
import natural_lab as nl  # noqa: E402

BASE = {"id": "base", "parent": None, "gen": 0, "seed": 338530958, "event": "base"}
GENERATIONS, CHILDREN = 3, 4


def evaluate(seed):
    params = nl.draw_params(random.Random(seed))
    obs_rng = random.Random(seed + 1)
    pred = nl.Predictor(params["stable_hits"])
    preds = []
    for i in range(params["length"]):
        obs = nl.make_observation(obs_rng, params, i)
        preds.append(pred.observe(dict(obs)))
    evaluated = [p for p in preds if p["detected"] is not None]
    acc = sum(p["detected"] == nl.regime_at(params, p["index"]) for p in evaluated) / len(evaluated)
    return params, round(acc, 4)


def run_tree():
    nodes = [dict(BASE)]
    fit = {}
    p0, fit["base"] = evaluate(BASE["seed"])
    frontier = [BASE]
    for gen in range(1, GENERATIONS + 1):
        nxt = []
        for parent in frontier:
            for k in range(CHILDREN):
                seed = random.Random(parent["seed"] * 1000 + k).randrange(2**31)
                child = {"id": f"g{gen}-{parent['id']}-{k}", "parent": parent["id"],
                         "gen": gen, "seed": seed, "event": "branch"}
                _, fit[child["id"]] = evaluate(seed)
                nodes.append(child)
                nxt.append(child)
        frontier = sorted(nxt, key=lambda c: -fit[c["id"]])[:2]  # keep 2 best per gen
    return nodes, fit


def main():
    out = Path(__file__).resolve().parent / "out"
    out.mkdir(exist_ok=True)
    nodes, fit = run_tree()
    lines = [json.dumps({**n, "accuracy": fit[n["id"]]}, ensure_ascii=False) for n in nodes]
    (out / "lineage.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    digest = hashlib.sha256((out / "lineage.jsonl").read_bytes()).hexdigest()
    print(f"nodes: {len(nodes)}  best: {max(fit, key=fit.get)} = {max(fit.values())}")
    print("lineage sha256:", digest)


if __name__ == "__main__":
    main()
