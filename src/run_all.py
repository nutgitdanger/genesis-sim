#!/usr/bin/env python3
"""
run_all.py  —  Genesis 4-Level Simulation Aggregator
=====================================================
Level 1 : Pattern / Regime Detection   (natural_lab)
Level 2 : Selection & Inheritance      (branch_sim + split_check)
Level 3 : Structure / Folding          (fold_sim HP-lattice)
Level 4 : Ecosystem Map                (root similarity scan)

Output layout
  genesis-runs/run-<ts>/
    records/
      L1-<ts>.jsonl
      L2-<ts>.jsonl
      L3-<ts>.jsonl
      L4-<ts>.jsonl
    summary/
      master.json     — every metric in one place
      sha256.json     — hash of every output file
      delta.json      — diff vs previous run (empty on first run)

Standalone: Python stdlib only. No network. No file mutation.
Seed: 338530958 (matches author device snapshot)
"""

from __future__ import annotations
import hashlib, json, math, os, random, sys, time
from datetime import datetime, timezone
from pathlib import Path

# ── global constants ─────────────────────────────────────────────────────
MASTER_SEED   = 338530958
OUT_ROOT      = Path.home() / "genesis-runs"
LAMBDA_WS     = 0.10          # penalty weight: wrong_switches in combined score
FOLD_ATTEMPTS = 400
FOLD_LENGTHS  = [12, 16, 20]
BRANCH_GENS   = 3
BRANCH_KIDS   = 4
SEL_SEEDS     = 20            # selection env seeds (L2)
HELD_SEEDS    = 30            # held-out env seeds  (L2)
HELD_DIFF_MIN = 0.0           # criterion: held-out mean diff > 0
HELD_FRAC_MIN = 0.5           # criterion: better on > half

# ── utilities ────────────────────────────────────────────────────────────
def utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()

def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8"
    )

# ════════════════════════════════════════════════════════════════════════
# LEVEL 1 — Pattern / Regime Detection
# ════════════════════════════════════════════════════════════════════════
L1_REGIMES   = ["horizontal", "vertical", "diagonal"]
L1_TEMPLATES = {
    r: [
        [1 if (
            (r == "horizontal" and j == 1) or
            (r == "vertical"   and i == 1) or
            (r == "diagonal"   and i == j)
        ) else 0 for j in range(3)]
        for i in range(3)
    ]
    for r in L1_REGIMES
}
L1_PHASES = 4

def _hamming(a, b):
    return sum(x != y for row_a, row_b in zip(a, b) for x, y in zip(row_a, row_b))

def _make_grid(regime, rng, noise):
    base = [row[:] for row in L1_TEMPLATES[regime]]
    for i in range(3):
        for j in range(3):
            if rng.random() < noise:
                base[i][j] ^= 1
    return base

def _classify(grid):
    best, best_r = 999, None
    for r in L1_REGIMES:
        for p in range(L1_PHASES):
            shifted = [row[:] for row in L1_TEMPLATES[r]]
            d = _hamming(grid, shifted)
            if d < best:
                best, best_r = d, r
    return best_r

def run_level1(seed) -> dict:
    rng = random.Random(seed)
    length     = rng.randint(120, 180)
    n_seg      = rng.randint(2, 5)
    noise      = rng.uniform(0, 0.05)
    stable_hit = rng.randint(2, 4)

    # build schedule
    breaks = sorted(rng.sample(range(1, length), n_seg - 1))
    starts = [0] + breaks
    ends   = breaks + [length]
    segs   = []
    for s, e in zip(starts, ends):
        segs.append({"start": s, "end": e,
                     "regime": rng.choice(L1_REGIMES),
                     "length": e - s})

    # simulate
    votes, correct_ev, total_ev = [], 0, 0
    wrong_switches, boundaries = [], []
    prev_declared = None

    for step in range(length):
        # find current truth
        truth = next(sg["regime"] for sg in segs
                     if sg["start"] <= step < sg["end"])
        grid = _make_grid(truth, rng, noise)
        pred = _classify(grid)
        votes.append(pred)

        if len(votes) >= stable_hit:
            window = votes[-stable_hit:]
            if len(set(window)) == 1:
                declared = window[0]
                total_ev += 1
                if declared == truth:
                    correct_ev += 1
                if prev_declared is not None and declared != prev_declared:
                    # check truth at switch
                    if declared != truth:
                        wrong_switches.append(step)
                    boundaries.append({"step": step, "new": declared,
                                       "truth": truth})
                prev_declared = declared

    acc = correct_ev / total_ev if total_ev else 0.0
    combined = acc - LAMBDA_WS * len(wrong_switches)

    return {
        "level": 1, "seed": seed,
        "length": length, "noise": round(noise, 6),
        "stable_hits": stable_hit, "segments": n_seg,
        "accuracy": round(acc, 6),
        "wrong_switch_count": len(wrong_switches),
        "wrong_switches": wrong_switches,
        "combined_score": round(combined, 6),
        "boundaries_detected": len(boundaries),
    }

# ════════════════════════════════════════════════════════════════════════
# LEVEL 2 — Selection & Inheritance
# ════════════════════════════════════════════════════════════════════════
def _child_seed(parent_seed, k):
    return random.Random(parent_seed * 1000 + k).randrange(2**31)

def _eval_genome(genome_seed, env_seed):
    r = run_level1(genome_seed ^ env_seed)
    return r["combined_score"], r["accuracy"], r["wrong_switch_count"]

def run_level2(seed) -> dict:
    rng = random.Random(seed)

    # fixed environment pools (disjoint)
    sel_envs  = [rng.randrange(2**31) for _ in range(SEL_SEEDS)]
    held_envs = [rng.randrange(2**31) for _ in range(HELD_SEEDS)]

    # candidate stable_hits values as genomes
    candidates = [2, 3, 4]

    # selection: mean combined score per candidate over sel_envs
    sel_scores = {}
    for c in candidates:
        scores = [_eval_genome(c, e)[0] for e in sel_envs]
        sel_scores[c] = round(sum(scores) / len(scores), 6)

    chosen = max(sel_scores, key=sel_scores.get)
    base   = min(candidates, key=lambda x: abs(x - 3))  # baseline = 3

    # held-out evaluation
    held_chosen = [_eval_genome(chosen, e)[0] for e in held_envs]
    held_base   = [_eval_genome(base,   e)[0] for e in held_envs]

    mean_chosen = sum(held_chosen) / len(held_chosen)
    mean_base   = sum(held_base)   / len(held_base)
    mean_diff   = mean_chosen - mean_base
    n_better    = sum(c > b for c, b in zip(held_chosen, held_base))
    frac_better = n_better / len(held_envs)

    criterion = mean_diff > HELD_DIFF_MIN and frac_better > HELD_FRAC_MIN

    # lineage branching from chosen genome
    base_node = {"id": "base", "seed": MASTER_SEED,
                 "gen": 0, "parent": None}
    lineage = [base_node]
    prev_gen = [base_node]

    for g in range(1, BRANCH_GENS + 1):
        next_gen = []
        for parent in prev_gen[:2]:
            children = []
            for k in range(BRANCH_KIDS):
                cseed = _child_seed(parent["seed"], k)
                score, acc, ws = _eval_genome(cseed, MASTER_SEED)
                node = {"id": f"g{g}-{parent['id']}-{k}",
                        "seed": cseed, "gen": g,
                        "parent": parent["id"],
                        "combined_score": round(score, 6),
                        "accuracy": round(acc, 6),
                        "wrong_switches": ws}
                children.append(node)
                lineage.append(node)
            children.sort(key=lambda x: x["combined_score"], reverse=True)
            next_gen.extend(children[:2])
        prev_gen = next_gen

    best = max((n for n in lineage if n.get("combined_score") is not None),
               key=lambda n: n["combined_score"])

    return {
        "level": 2, "seed": seed,
        "sel_scores": {str(k): v for k, v in sel_scores.items()},
        "chosen_genome": chosen,
        "base_genome": base,
        "held_mean_chosen": round(mean_chosen, 6),
        "held_mean_base": round(mean_base, 6),
        "held_mean_diff": round(mean_diff, 6),
        "held_frac_better": round(frac_better, 6),
        "criterion_passed": criterion,
        "lineage_nodes": len(lineage),
        "best_node_id": best["id"],
        "best_combined_score": best["combined_score"],
        "lineage": lineage,
    }

# ════════════════════════════════════════════════════════════════════════
# LEVEL 3 — Structure / Folding (HP-lattice)
# ════════════════════════════════════════════════════════════════════════
_DIRS = [(1,0),(-1,0),(0,1),(0,-1)]

def _fold(seq, seed):
    n = len(seq)
    rng = random.Random(seed)
    pos = [(0,0)]
    occ = {(0,0): 0}
    for i in range(1, n):
        dirs = _DIRS[:]
        rng.shuffle(dirs)
        placed = False
        for d in dirs:
            nx, ny = pos[-1][0]+d[0], pos[-1][1]+d[1]
            if (nx,ny) not in occ:
                pos.append((nx,ny)); occ[(nx,ny)] = i; placed = True; break
        if not placed:
            return pos, 0, False
    energy = 0
    for i,(x,y) in enumerate(pos):
        if seq[i] != 1: continue
        for d in _DIRS:
            nb = (x+d[0],y+d[1])
            j = occ.get(nb,-1)
            if j == -1 or abs(j-i)==1: continue
            if seq[j]==1: energy -= 1
    energy //= 2
    return pos, energy, energy <= -4

def _make_seq(seed, length):
    rng = random.Random(seed)
    return [rng.randint(0,1) for _ in range(length)]

def _crossover(sA, sB, rng):
    cut = rng.randint(1, len(sA)-1)
    return sA[:cut] + sB[cut:]

def run_level3(seed) -> dict:
    rng = random.Random(seed)
    rows = []

    for length in FOLD_LENGTHS:
        # gen 0
        s0 = rng.randrange(2**31)
        seq0 = _make_seq(s0, length)
        _, e0, ok0 = _fold(seq0, s0)
        rows.append({"gen":0,"seed":s0,"length":length,"energy":e0,
                     "success":ok0,"parent":None,"type":"original"})

        survivors = [(s0, seq0, e0, ok0)]
        for g in range(1, BRANCH_GENS+1):
            gen_rows = []
            for pseed, pseq, _, _ in survivors:
                for k in range(BRANCH_KIDS):
                    cseed = _child_seed(pseed, k)
                    cseq = _make_seq(cseed, length)
                    _, ce, cok = _fold(cseq, cseed)
                    gen_rows.append({"gen":g,"seed":cseed,"length":length,
                                     "energy":ce,"success":cok,
                                     "parent":pseed,"type":"child"})
                    rows.append(gen_rows[-1])
            gen_rows.sort(key=lambda x: x["energy"])
            survivors = [(r["seed"], _make_seq(r["seed"],length),
                          r["energy"], r["success"]) for r in gen_rows[:2]]

        # crossover
        if len(survivors) >= 2:
            crng = random.Random(survivors[0][0] ^ survivors[1][0])
            cseq = _crossover(survivors[0][1], survivors[1][1], crng)
            xseed = crng.randrange(2**31)
            _, xe, xok = _fold(cseq, xseed)
            rows.append({"gen":BRANCH_GENS+1,"seed":xseed,"length":length,
                         "energy":xe,"success":xok,
                         "parent":f"{survivors[0][0]}+{survivors[1][0]}",
                         "type":"crossover"})

    total   = len(rows)
    success = sum(1 for r in rows if r["success"])
    best    = min(rows, key=lambda r: r["energy"])

    return {
        "level": 3, "seed": seed,
        "total_records": total,
        "successful_folds": success,
        "success_rate": round(success/total, 4),
        "best_energy": best["energy"],
        "best_seed": best["seed"],
        "best_length": best["length"],
        "fold_records": rows,
    }

# ════════════════════════════════════════════════════════════════════════
# LEVEL 4 — Ecosystem Map (structural similarity)
# ════════════════════════════════════════════════════════════════════════
def _jaccard(a: set, b: set) -> float:
    if not a and not b: return 0.0
    return len(a & b) / len(a | b)

def run_level4(seed) -> dict:
    """
    Synthetic ecosystem: each node has a random role set.
    Computes pairwise Jaccard similarity → flow graph.
    """
    rng  = random.Random(seed)
    ROLES = ["GENOME","MESSENGER","PROCESSOR","VECTOR",
             "GUARDIAN","OBSERVER","METABOLISM","MEMORY",
             "TRANSPORT","RECOVERY"]
    N = 20

    nodes = []
    for i in range(N):
        n_roles = rng.randint(1, 5)
        nodes.append({
            "id": f"node-{i:02d}",
            "roles": set(rng.sample(ROLES, n_roles)),
        })

    pairs = []
    for i in range(N):
        for j in range(i+1, N):
            sim = _jaccard(nodes[i]["roles"], nodes[j]["roles"])
            if sim >= 0.20:
                pairs.append({
                    "source": nodes[i]["id"],
                    "target": nodes[j]["id"],
                    "similarity": round(sim, 4),
                    "shared_roles": sorted(
                        nodes[i]["roles"] & nodes[j]["roles"]),
                })

    pairs.sort(key=lambda x: x["similarity"], reverse=True)

    # mass flow: each node starts with 1.0
    mass = {n["id"]: 1.0 for n in nodes}
    FLOW_STEPS = 10
    ALPHA = 0.05  # fraction transferred per step per edge
    mass_history = [sum(mass.values())]

    for _ in range(FLOW_STEPS):
        delta = {nid: 0.0 for nid in mass}
        for p in pairs:
            transfer = ALPHA * p["similarity"] * mass[p["source"]]
            delta[p["source"]] -= transfer
            delta[p["target"]] += transfer
        for nid in mass:
            mass[nid] = max(0.0, mass[nid] + delta[nid])
        mass_history.append(round(sum(mass.values()), 8))

    mass_initial = mass_history[0]
    mass_final   = mass_history[-1]
    conserved    = abs(mass_final - mass_initial) < 1e-6

    isolated = sum(1 for n in nodes
                   if not any(p["source"]==n["id"] or p["target"]==n["id"]
                               for p in pairs))

    return {
        "level": 4, "seed": seed,
        "nodes": N,
        "similarity_pairs": len(pairs),
        "graph_density": round(len(pairs) / (N*(N-1)/2), 4),
        "isolated_nodes": isolated,
        "flow_steps": FLOW_STEPS,
        "mass_initial": mass_initial,
        "mass_final": round(mass_final, 8),
        "mass_conserved": conserved,
        "mass_loss_pct": round(abs(mass_final-mass_initial)/mass_initial*100, 4),
        "top_pairs": pairs[:10],
        "node_roles": [
            {"id": n["id"], "roles": sorted(n["roles"])} for n in nodes],
    }

# ════════════════════════════════════════════════════════════════════════
# AGGREGATOR
# ════════════════════════════════════════════════════════════════════════
def load_prev_summary(run_dir: Path):
    runs = sorted(OUT_ROOT.glob("run-*"))
    # exclude current
    prev = [r for r in runs if r != run_dir and
            (r / "summary" / "master.json").exists()]
    if not prev:
        return None
    latest = prev[-1] / "summary" / "master.json"
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None

def make_delta(current: dict, prev: dict | None) -> dict:
    if prev is None:
        return {"previous_run": None, "delta": "first_run"}

    keys = ["L1_accuracy","L1_wrong_switches","L1_combined_score",
            "L2_criterion_passed","L2_held_mean_diff","L2_best_combined",
            "L3_success_rate","L3_best_energy",
            "L4_graph_density","L4_mass_conserved"]
    delta = {}
    for k in keys:
        c = current.get(k)
        p = prev.get(k)
        if isinstance(c, (int,float)) and isinstance(p, (int,float)):
            delta[k] = {"prev": p, "curr": c,
                        "diff": round(c - p, 6)}
        elif c != p:
            delta[k] = {"prev": p, "curr": c}
    return {"previous_run": prev.get("run_id"), "delta": delta}

# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════
def main():
    ts      = utc_ts()
    run_dir = OUT_ROOT / f"run-{ts}"
    rec_dir = run_dir / "records"
    sum_dir = run_dir / "summary"
    rec_dir.mkdir(parents=True, exist_ok=True)
    sum_dir.mkdir(parents=True, exist_ok=True)

    print(f"Genesis 4-Level Simulation  run={ts}  seed={MASTER_SEED}")
    print("=" * 60)

    t0 = time.time()

    # ── Level 1 ──────────────────────────────────────────────
    print("[L1] Pattern / Regime Detection ...")
    l1 = run_level1(MASTER_SEED)
    write_jsonl(rec_dir / f"L1-{ts}.jsonl", [l1])
    print(f"     accuracy={l1['accuracy']}  wrong_sw={l1['wrong_switch_count']}"
          f"  combined={l1['combined_score']}")

    # ── Level 2 ──────────────────────────────────────────────
    print("[L2] Selection & Inheritance ...")
    l2 = run_level2(MASTER_SEED)
    # strip large lineage from jsonl line, keep in master
    l2_slim = {k: v for k, v in l2.items() if k != "lineage"}
    write_jsonl(rec_dir / f"L2-{ts}.jsonl", [l2_slim])
    # full lineage as separate file
    write_jsonl(rec_dir / f"L2-lineage-{ts}.jsonl", l2["lineage"])
    print(f"     criterion={l2['criterion_passed']}"
          f"  held_diff={l2['held_mean_diff']}"
          f"  best_score={l2['best_combined_score']}")

    # ── Level 3 ──────────────────────────────────────────────
    print("[L3] Structure / Folding ...")
    l3 = run_level3(MASTER_SEED)
    l3_slim = {k: v for k, v in l3.items() if k != "fold_records"}
    write_jsonl(rec_dir / f"L3-{ts}.jsonl", [l3_slim])
    write_jsonl(rec_dir / f"L3-folds-{ts}.jsonl", l3["fold_records"])
    print(f"     success={l3['successful_folds']}/{l3['total_records']}"
          f"  rate={l3['success_rate']}"
          f"  best_energy={l3['best_energy']}")

    # ── Level 4 ──────────────────────────────────────────────
    print("[L4] Ecosystem Map ...")
    l4 = run_level4(MASTER_SEED)
    l4_slim = {k: v for k, v in l4.items()
               if k not in ("top_pairs","node_roles")}
    write_jsonl(rec_dir / f"L4-{ts}.jsonl", [l4_slim])
    write_json(sum_dir / "ecosystem_graph.json",
               {"nodes": l4["node_roles"], "top_pairs": l4["top_pairs"]})
    print(f"     pairs={l4['similarity_pairs']}"
          f"  density={l4['graph_density']}"
          f"  mass_conserved={l4['mass_conserved']}")

    elapsed = round(time.time() - t0, 3)

    # ── master.json ──────────────────────────────────────────
    master = {
        "run_id": ts,
        "master_seed": MASTER_SEED,
        "lambda_ws": LAMBDA_WS,
        "elapsed_seconds": elapsed,
        "python": sys.version.split()[0],
        # L1
        "L1_accuracy":        l1["accuracy"],
        "L1_wrong_switches":  l1["wrong_switch_count"],
        "L1_combined_score":  l1["combined_score"],
        "L1_noise":           l1["noise"],
        "L1_stable_hits":     l1["stable_hits"],
        # L2
        "L2_criterion_passed":l2["criterion_passed"],
        "L2_held_mean_diff":  l2["held_mean_diff"],
        "L2_held_frac_better":l2["held_frac_better"],
        "L2_chosen_genome":   l2["chosen_genome"],
        "L2_best_combined":   l2["best_combined_score"],
        "L2_lineage_nodes":   l2["lineage_nodes"],
        # L3
        "L3_total_folds":     l3["total_records"],
        "L3_success_folds":   l3["successful_folds"],
        "L3_success_rate":    l3["success_rate"],
        "L3_best_energy":     l3["best_energy"],
        # L4
        "L4_nodes":           l4["nodes"],
        "L4_pairs":           l4["similarity_pairs"],
        "L4_graph_density":   l4["graph_density"],
        "L4_isolated":        l4["isolated_nodes"],
        "L4_mass_conserved":  l4["mass_conserved"],
        "L4_mass_loss_pct":   l4["mass_loss_pct"],
    }
    write_json(sum_dir / "master.json", master)

    # ── sha256.json ──────────────────────────────────────────
    hashes = {}
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.name != "sha256.json":
            hashes[str(p.relative_to(run_dir))] = sha256_file(p)
    write_json(sum_dir / "sha256.json", hashes)

    # ── delta.json ───────────────────────────────────────────
    prev = load_prev_summary(run_dir)
    delta = make_delta(master, prev)
    write_json(sum_dir / "delta.json", delta)

    # ── final print ──────────────────────────────────────────
    run_sha = sha256_bytes(
        json.dumps(master, sort_keys=True).encode())
    print("=" * 60)
    print(f"elapsed   : {elapsed}s")
    print(f"run sha256: {run_sha}")
    print(f"output    : {run_dir}")
    print(f"delta     : {'first run' if prev is None else delta.get('previous_run')}")

    # print master table
    print("\n── master summary ──────────────────────────────────────")
    COL = 28
    for k, v in master.items():
        if k in ("run_id","master_seed","python","elapsed_seconds"): continue
        print(f"  {k:<{COL}} {v}")

if __name__ == "__main__":
    main()
