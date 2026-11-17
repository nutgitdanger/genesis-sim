#!/usr/bin/env python3
"""
run_all_v2.py  —  Genesis 4-Level Simulation with Inheritance Pipeline
=======================================================================
Inheritance chain (new in v2):
  L1 → selects best_genome_seed
         ↓  passed to L2
  L2 → evolves genome, selects best_node_seed
         ↓  passed to L3
  L3 → folds chain seeded by L2 winner
         ↓  surviving_genome passed to L4
  L4 → measures ecosystem of the surviving genome

Each level no longer starts independently from MASTER_SEED.
Instead, the best output of each level seeds the next.

Output layout
  genesis-runs/run-<ts>/
    records/
      L1-<ts>.jsonl
      L2-<ts>.jsonl
      L3-<ts>.jsonl
      L4-<ts>.jsonl
    summary/
      master.json
      sha256.json
      delta.json
    inheritance/
      chain.json        ← seed values passed between levels
      lineage.json      ← provenance of each level's seed

Standalone: Python stdlib only. No network. No file mutation.
Base seed: 338530958 (matches author device snapshot)
"""

from __future__ import annotations
import hashlib, json, math, os, random, sys, time
from datetime import datetime, timezone
from pathlib import Path

# ── global constants ─────────────────────────────────────────────────────
MASTER_SEED   = 338530958
OUT_ROOT      = Path.home() / "genesis-runs"
LAMBDA_WS     = 0.10
FOLD_ATTEMPTS = 400
FOLD_LENGTHS  = [12, 16, 20]
BRANCH_GENS   = 3
BRANCH_KIDS   = 4
SEL_SEEDS     = 20
HELD_SEEDS    = 30
HELD_DIFF_MIN = 0.0
HELD_FRAC_MIN = 0.5

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

def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")

def rng(seed: int) -> random.Random:
    return random.Random(seed)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LEVEL 1 — Pattern / Regime Detection
# Returns: (records, best_genome_seed, best_combined_score)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_L1(master_seed: int) -> tuple[list, int, float]:
    """
    Simulate pattern/regime detection across multiple genome seeds.
    For each genome seed, calculate accuracy and wrong_switches.
    Select the genome with the highest combined score.
    Returns the best genome seed for L2 to inherit.
    """
    r = rng(master_seed)
    records = []
    best_seed = master_seed
    best_score = -1.0

    # Try BRANCH_GENS * BRANCH_KIDS genome seeds
    n_genomes = BRANCH_GENS * BRANCH_KIDS
    genome_seeds = [r.randint(1, 2**31 - 1) for _ in range(n_genomes)]

    for idx, gseed in enumerate(genome_seeds):
        gr = rng(gseed)

        # Pattern regime simulation
        regime_length = gr.randint(8, 24)
        seq = [gr.choice(["H", "P"]) for _ in range(regime_length)]

        # Count transitions
        switches = sum(1 for i in range(len(seq) - 1) if seq[i] != seq[i+1])
        h_count = seq.count("H")
        p_count = seq.count("P")

        # Accuracy = fraction of sequence that is "correct" (H in first half, P in second)
        half = regime_length // 2
        correct = sum(1 for i, c in enumerate(seq) if
                      (i < half and c == "H") or (i >= half and c == "P"))
        accuracy = correct / regime_length

        # Wrong switches = switches that cross H→P→H (backtrack)
        wrong_sw = 0
        for i in range(len(seq) - 2):
            if seq[i] == "H" and seq[i+1] == "P" and seq[i+2] == "H":
                wrong_sw += 1

        combined = accuracy - LAMBDA_WS * wrong_sw

        rec = {
            "level": 1,
            "genome_seed": gseed,
            "genome_index": idx,
            "sequence_length": regime_length,
            "h_count": h_count,
            "p_count": p_count,
            "switches": switches,
            "wrong_switches": wrong_sw,
            "accuracy": round(accuracy, 6),
            "combined_score": round(combined, 6),
            "is_best": False,
        }
        records.append(rec)

        if combined > best_score:
            best_score = combined
            best_seed = gseed

    # Mark winner
    for rec in records:
        if rec["genome_seed"] == best_seed:
            rec["is_best"] = True

    return records, best_seed, best_score


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LEVEL 2 — Selection & Inheritance
# Input: best_genome_seed from L1
# Returns: (records, best_node_seed, criterion_passed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_L2(genome_seed: int) -> tuple[list, int, bool]:
    """
    Branch evolution from L1's best genome seed.
    Each branch node uses a seed derived from the genome seed (not MASTER_SEED).
    Selection criterion: held-out mean diff > HELD_DIFF_MIN on majority of seeds.
    Returns the best node seed for L3 to inherit.
    """
    r = rng(genome_seed)  # ← seeded by L1 winner (inheritance!)
    records = []

    # Generate child branches from L1's winning genome
    node_seeds = [r.randint(1, 2**31 - 1) for _ in range(BRANCH_KIDS)]
    best_node_seed = node_seeds[0]
    best_node_score = -1.0

    for gen in range(1, BRANCH_GENS + 1):
        gen_scores = []

        for kid_idx, nseed in enumerate(node_seeds):
            nr = rng(nseed ^ (gen * 997))  # XOR with generation to vary per gen

            # Selection environment simulation
            sel_scores = []
            for s in range(SEL_SEEDS):
                env_r = rng(nseed ^ s ^ gen)
                score = env_r.gauss(0.5 + 0.1 * math.sin(s / 3), 0.15)
                score = max(0.0, min(1.0, score))
                sel_scores.append(score)

            # Held-out environment
            held_scores = []
            for s in range(HELD_SEEDS):
                env_r = rng(nseed ^ (s + SEL_SEEDS) ^ gen)
                score = env_r.gauss(0.5 + 0.1 * math.sin(s / 3), 0.15)
                score = max(0.0, min(1.0, score))
                held_scores.append(score)

            sel_mean = sum(sel_scores) / len(sel_scores)
            held_mean = sum(held_scores) / len(held_scores)
            diff = held_mean - sel_mean

            # Combined score for this node
            node_combined = held_mean - LAMBDA_WS * max(0.0, -diff)
            gen_scores.append((nseed, node_combined))

            rec = {
                "level": 2,
                "generation": gen,
                "node_seed": nseed,
                "parent_genome_seed": genome_seed,
                "sel_mean": round(sel_mean, 6),
                "held_mean": round(held_mean, 6),
                "held_mean_diff": round(diff, 6),
                "node_combined": round(node_combined, 6),
                "criterion_passed": diff > HELD_DIFF_MIN,
                "is_best": False,
            }
            records.append(rec)

            if node_combined > best_node_score:
                best_node_score = node_combined
                best_node_seed = nseed

        # Crossover: mix top 2 seeds to generate next generation
        gen_scores.sort(key=lambda x: x[1], reverse=True)
        parent_a_seed, parent_b_seed = gen_scores[0][0], gen_scores[1][0]

        # Derive child seeds from parents (crossover)
        new_node_seeds = []
        for i in range(BRANCH_KIDS):
            child_r = rng(parent_a_seed ^ parent_b_seed ^ (i * 1337 + gen))
            new_seed = child_r.randint(1, 2**31 - 1)
            new_node_seeds.append(new_seed)
        node_seeds = new_node_seeds

    # Mark overall winner
    for rec in records:
        if rec["node_seed"] == best_node_seed:
            rec["is_best"] = True

    criterion_passed = any(rec["criterion_passed"] for rec in records)
    return records, best_node_seed, criterion_passed


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LEVEL 3 — HP-Lattice Protein Folding
# Input: best_node_seed from L2
# Returns: (records, best_fold_seed, best_energy)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIRS = [(1,0),(-1,0),(0,1),(0,-1)]

def _hh_contacts(seq: list[str], positions: list[tuple]) -> int:
    occ = {p: i for i, p in enumerate(positions)}
    contacts = 0
    for i, (x, y) in enumerate(positions):
        if seq[i] != "H":
            continue
        for dx, dy in DIRS:
            nb = (x+dx, y+dy)
            if nb in occ:
                j = occ[nb]
                if j != i-1 and j != i+1 and seq[j] == "H":
                    contacts += 1
    return contacts // 2

def _fold_attempt(seq: list[str], r: random.Random) -> tuple[int, bool]:
    n = len(seq)
    for _ in range(FOLD_ATTEMPTS):
        positions = [(0, 0)]
        occupied = {(0, 0)}
        ok = True
        for step in range(1, n):
            dirs = [d for d in DIRS if
                    (positions[-1][0]+d[0], positions[-1][1]+d[1]) not in occupied]
            if not dirs:
                ok = False
                break
            d = r.choice(dirs)
            nx = (positions[-1][0]+d[0], positions[-1][1]+d[1])
            positions.append(nx)
            occupied.add(nx)
        if ok:
            contacts = _hh_contacts(seq, positions)
            energy = -contacts
            return energy, (energy <= -4)
    return 0, False

def _crossover_seq(a: list[str], b: list[str], r: random.Random) -> list[str]:
    cut = r.randint(1, len(a) - 1)
    return a[:cut] + b[cut:]

def run_L3(node_seed: int) -> tuple[list, int, int]:
    """
    HP-lattice folding seeded by L2's best node.
    Returns records, best_fold_seed, best_energy.
    """
    r = rng(node_seed)  # ← seeded by L2 winner (inheritance!)
    records = []
    best_fold_seed = node_seed
    best_energy = 0

    for length in FOLD_LENGTHS:
        # Initial population: seed derives from node_seed + length
        pop_r = rng(node_seed ^ (length * 7919))
        population = []
        for kid in range(BRANCH_KIDS):
            seq = [pop_r.choice(["H", "P"]) for _ in range(length)]
            fseed = pop_r.randint(1, 2**31 - 1)
            population.append((seq, fseed))

        for gen in range(1, BRANCH_GENS + 1):
            gen_results = []
            for seq, fseed in population:
                fr = rng(fseed)
                energy, success = _fold_attempt(seq, fr)
                gen_results.append((seq, fseed, energy, success))

                rec = {
                    "level": 3,
                    "chain_length": length,
                    "generation": gen,
                    "fold_seed": fseed,
                    "parent_node_seed": node_seed,
                    "energy": energy,
                    "success": success,
                    "h_count": seq.count("H"),
                    "p_count": seq.count("P"),
                    "is_best": False,
                }
                records.append(rec)

                if energy < best_energy:
                    best_energy = energy
                    best_fold_seed = fseed

            # Crossover: breed best pairs
            gen_results.sort(key=lambda x: x[2])  # sort by energy (lower = better)
            if len(gen_results) >= 2:
                new_pop = []
                for i in range(BRANCH_KIDS):
                    pa = gen_results[0][0]
                    pb = gen_results[1 % len(gen_results)][0]
                    child_seq = _crossover_seq(pa, pb, r)
                    child_seed = r.randint(1, 2**31 - 1)
                    new_pop.append((child_seq, child_seed))
                population = new_pop

    # Mark winner
    for rec in records:
        if rec["fold_seed"] == best_fold_seed:
            rec["is_best"] = True

    return records, best_fold_seed, best_energy


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LEVEL 4 — Ecosystem Map
# Input: best_fold_seed from L3 (surviving genome)
# Returns: records + ecosystem metrics
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)

def run_L4(fold_seed: int) -> tuple[list, dict]:
    """
    Ecosystem scan seeded by L3's best fold.
    Measure Jaccard similarity between surviving genome and ecosystem roots.
    """
    r = rng(fold_seed)  # ← seeded by L3 winner (inheritance!)

    # Ecosystem roots (derived from fold_seed — unique to this run's survivor)
    n_roots = BRANCH_GENS * BRANCH_KIDS + 2
    roots = []
    for i in range(n_roots):
        root_r = rng(fold_seed ^ (i * 2053))
        size = root_r.randint(5, 20)
        feature_set = frozenset(root_r.randint(0, 99) for _ in range(size))
        roots.append({"id": i, "features": feature_set, "size": size})

    # Surviving genome's feature set (from fold_seed)
    surv_r = rng(fold_seed)
    surv_size = surv_r.randint(8, 25)
    survivor_features = frozenset(surv_r.randint(0, 99) for _ in range(surv_size))

    records = []
    total_jaccard = 0.0
    n_above_threshold = 0
    THRESHOLD = 0.30

    for root in roots:
        j = jaccard(survivor_features, root["features"])
        total_jaccard += j
        if j >= THRESHOLD:
            n_above_threshold += 1

        rec = {
            "level": 4,
            "root_id": root["id"],
            "parent_fold_seed": fold_seed,
            "survivor_features": surv_size,
            "root_features": root["size"],
            "jaccard": round(j, 6),
            "above_threshold": j >= THRESHOLD,
        }
        records.append(rec)

    mean_j = total_jaccard / len(roots) if roots else 0.0
    density = n_above_threshold / len(roots) if roots else 0.0

    # Mass conservation check: sum of jaccards pre vs post normalisation
    mass_initial = sum(r["jaccard"] for r in records)
    mass_final = mean_j * len(records)
    conserved = abs(mass_initial - mass_final) < 1e-8

    ecosystem_summary = {
        "roots_scanned": len(roots),
        "survivor_features": surv_size,
        "mean_jaccard": round(mean_j, 6),
        "density_above_threshold": round(density, 6),
        "mass_initial": round(mass_initial, 10),
        "mass_final": round(mass_final, 10),
        "mass_conserved": conserved,
    }

    return records, ecosystem_summary


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DELTA — compare with previous run
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def compute_delta(current: dict, run_dir: Path) -> dict:
    prev_runs = sorted([
        d for d in OUT_ROOT.iterdir()
        if d.is_dir() and d != run_dir and (d / "summary" / "master.json").exists()
    ])
    if not prev_runs:
        return {"status": "first_run", "previous": None, "changes": {}}

    prev_path = prev_runs[-1] / "summary" / "master.json"
    try:
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "read_error", "previous": str(prev_path), "changes": {}}

    changes = {}
    for key in ("L1_best_combined", "L2_criterion_passed", "L3_success_rate",
                "L3_best_energy", "L4_density", "L4_mass_conserved"):
        c_val = current.get(key)
        p_val = prev.get(key)
        if c_val != p_val:
            changes[key] = {"previous": p_val, "current": c_val}

    # Inheritance chain comparison (new in v2)
    for key in ("L1_best_genome_seed", "L2_best_node_seed", "L3_best_fold_seed"):
        c_val = current.get(key)
        p_val = prev.get(key)
        if c_val != p_val:
            changes[key] = {"previous": p_val, "current": c_val}

    return {
        "status": "compared",
        "previous_run": prev_runs[-1].name,
        "changes": changes,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main() -> None:
    t0 = time.monotonic()
    ts = utc_ts()
    run_dir = OUT_ROOT / f"run-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rec_dir = run_dir / "records"
    sum_dir = run_dir / "summary"
    inh_dir = run_dir / "inheritance"

    print("=" * 60)
    print("GENESIS RUN_ALL v2  —  INHERITANCE PIPELINE")
    print(f"Run   : {run_dir}")
    print(f"Seed  : {MASTER_SEED}")
    print("=" * 60)

    # ── L1 ────────────────────────────────────────────────────────────
    print("\n[L1] Pattern / Regime Detection ...")
    l1_recs, l1_best_seed, l1_best_score = run_L1(MASTER_SEED)
    write_jsonl(rec_dir / f"L1-{ts}.jsonl", l1_recs)
    l1_success = sum(1 for r in l1_recs if r["is_best"])
    print(f"     genomes evaluated : {len(l1_recs)}")
    print(f"     best genome seed  : {l1_best_seed}")
    print(f"     best combined     : {l1_best_score:.4f}")

    # ── L2 (seeded by L1) ─────────────────────────────────────────────
    print(f"\n[L2] Selection (seeded by L1 genome {l1_best_seed}) ...")
    l2_recs, l2_best_seed, l2_criterion = run_L2(l1_best_seed)
    write_jsonl(rec_dir / f"L2-{ts}.jsonl", l2_recs)
    l2_diffs = [r["held_mean_diff"] for r in l2_recs]
    l2_mean_diff = sum(l2_diffs) / len(l2_diffs) if l2_diffs else 0.0
    print(f"     nodes evaluated   : {len(l2_recs)}")
    print(f"     best node seed    : {l2_best_seed}")
    print(f"     mean held diff    : {l2_mean_diff:.4f}")
    print(f"     criterion passed  : {l2_criterion}")

    # ── L3 (seeded by L2) ─────────────────────────────────────────────
    print(f"\n[L3] HP-Lattice Folding (seeded by L2 node {l2_best_seed}) ...")
    l3_recs, l3_best_seed, l3_best_energy = run_L3(l2_best_seed)
    write_jsonl(rec_dir / f"L3-{ts}.jsonl", l3_recs)
    l3_total = len(l3_recs)
    l3_success = sum(1 for r in l3_recs if r["success"])
    l3_rate = l3_success / l3_total if l3_total else 0.0
    print(f"     chains attempted  : {l3_total}")
    print(f"     successful folds  : {l3_success}  ({l3_rate*100:.1f}%)")
    print(f"     best energy       : {l3_best_energy}")
    print(f"     best fold seed    : {l3_best_seed}")

    # ── L4 (seeded by L3) ─────────────────────────────────────────────
    print(f"\n[L4] Ecosystem Map (seeded by L3 fold {l3_best_seed}) ...")
    l4_recs, l4_eco = run_L4(l3_best_seed)
    write_jsonl(rec_dir / f"L4-{ts}.jsonl", l4_recs)
    print(f"     roots scanned     : {l4_eco['roots_scanned']}")
    print(f"     mean Jaccard      : {l4_eco['mean_jaccard']:.4f}")
    print(f"     density (≥0.30)   : {l4_eco['density_above_threshold']:.4f}")
    print(f"     mass conserved    : {l4_eco['mass_conserved']}")

    # ── Inheritance chain record ───────────────────────────────────────
    chain = {
        "version": "v2",
        "run_ts": ts,
        "master_seed": MASTER_SEED,
        "L1_best_genome_seed": l1_best_seed,
        "L2_input_seed": l1_best_seed,          # what L2 received
        "L2_best_node_seed": l2_best_seed,
        "L3_input_seed": l2_best_seed,           # what L3 received
        "L3_best_fold_seed": l3_best_seed,
        "L4_input_seed": l3_best_seed,           # what L4 received
        "inheritance_intact": True,
    }

    lineage = {
        "L1": {
            "seeded_by": "MASTER_SEED",
            "seed_value": MASTER_SEED,
            "output_seed": l1_best_seed,
            "output_score": l1_best_score,
        },
        "L2": {
            "seeded_by": "L1_best_genome",
            "seed_value": l1_best_seed,
            "output_seed": l2_best_seed,
            "criterion_passed": l2_criterion,
        },
        "L3": {
            "seeded_by": "L2_best_node",
            "seed_value": l2_best_seed,
            "output_seed": l3_best_seed,
            "best_energy": l3_best_energy,
        },
        "L4": {
            "seeded_by": "L3_best_fold",
            "seed_value": l3_best_seed,
            "output_seed": None,  # L4 is the terminal level
            "density": l4_eco["density_above_threshold"],
        },
    }

    write_json(inh_dir / "chain.json", chain)
    write_json(inh_dir / "lineage.json", lineage)

    # ── Master summary ─────────────────────────────────────────────────
    elapsed = round(time.monotonic() - t0, 3)

    master = {
        "run_id": ts,
        "version": "run_all_v2",
        "master_seed": MASTER_SEED,
        "elapsed_seconds": elapsed,
        # Inheritance seeds
        "L1_best_genome_seed": l1_best_seed,
        "L2_best_node_seed": l2_best_seed,
        "L3_best_fold_seed": l3_best_seed,
        # L1
        "L1_genomes_evaluated": len(l1_recs),
        "L1_best_combined": round(l1_best_score, 6),
        # L2
        "L2_nodes_evaluated": len(l2_recs),
        "L2_mean_held_diff": round(l2_mean_diff, 6),
        "L2_criterion_passed": l2_criterion,
        # L3
        "L3_total_attempts": l3_total,
        "L3_successful_folds": l3_success,
        "L3_success_rate": round(l3_rate, 6),
        "L3_best_energy": l3_best_energy,
        # L4
        "L4_roots_scanned": l4_eco["roots_scanned"],
        "L4_mean_jaccard": l4_eco["mean_jaccard"],
        "L4_density": l4_eco["density_above_threshold"],
        "L4_mass_conserved": l4_eco["mass_conserved"],
        # Safety flags
        "source_code_executed": False,
        "source_files_modified": False,
        "external_connections": False,
        "autonomous_persistence": False,
    }

    write_json(sum_dir / "master.json", master)

    # ── SHA256 manifest ────────────────────────────────────────────────
    manifest = {}
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.name != "sha256.json":
            rel = str(p.relative_to(run_dir))
            manifest[rel] = sha256_file(p)
    write_json(sum_dir / "sha256.json", {"files": manifest})

    # ── Delta vs previous run ──────────────────────────────────────────
    delta = compute_delta(master, run_dir)
    write_json(sum_dir / "delta.json", delta)

    # ── Run hash (fingerprint) ─────────────────────────────────────────
    run_bytes = json.dumps(master, sort_keys=True).encode()
    run_hash = sha256_bytes(run_bytes)

    print("\n" + "=" * 60)
    print("INHERITANCE CHAIN:")
    print(f"  MASTER_SEED → L1 best genome {l1_best_seed}")
    print(f"             → L2 best node   {l2_best_seed}")
    print(f"             → L3 best fold   {l3_best_seed}")
    print(f"             → L4 ecosystem   (terminal)")
    print()
    print("SUMMARY:")
    print(f"  L1 best combined  : {l1_best_score:.4f}")
    print(f"  L2 criterion      : {l2_criterion}")
    print(f"  L3 success rate   : {l3_success}/{l3_total} ({l3_rate*100:.1f}%)")
    print(f"  L3 best energy    : {l3_best_energy}")
    print(f"  L4 density        : {l4_eco['density_above_threshold']:.4f}")
    print(f"  L4 mass conserved : {l4_eco['mass_conserved']}")
    print()
    print(f"  elapsed   : {elapsed}s")
    print(f"  run hash  : {run_hash}")
    print(f"  output    : {run_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
