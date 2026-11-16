"""
fold_sim.py  –  HP-lattice bead-chain folding simulator
seed / environment matched to author device snapshot (seed 338530958)

Model: 2-D square lattice, beads = H (hydrophobic=1) or P (polar=0)
Energy = -1 for each H-H contact that is not backbone-adjacent
Fold attempt = Monte-Carlo random-walk with greedy acceptance
SUCCESS criterion: energy <= ENERGY_GOAL (pre-registered)
"""

import random, json, hashlib, time, itertools
from pathlib import Path

# ── pre-registered constants ──────────────────────────────────────────────
MASTER_SEED   = 338530958        # matches author device seed
CHAIN_LENGTHS = [12, 16, 20]     # bead counts per experiment
ATTEMPTS      = 400              # MC steps per fold attempt
ENERGY_GOAL   = -4               # success threshold (≥4 H-H contacts)
GENERATIONS   = 3
CHILDREN      = 4
LAMBDA        = 0.1              # penalty weight on wrong-fold-count (unused here, reserved)
# ─────────────────────────────────────────────────────────────────────────

DIRECTIONS = [(1,0),(-1,0),(0,1),(0,-1)]

def make_sequence(rng, length):
    """Binary H/P sequence; ~50 % hydrophobic."""
    return [rng.randint(0, 1) for _ in range(length)]

def fold(sequence, rng, steps=ATTEMPTS):
    """
    Self-avoiding random walk on 2-D lattice.
    Returns (coords, energy, success).
    coords = list of (x,y); energy = count of non-bonded H-H contacts * -1.
    """
    n = len(sequence)
    pos = [(0, 0)]
    occupied = {(0, 0): 0}

    for i in range(1, n):
        random.shuffle(DIRECTIONS)          # local shuffle via passed rng
        placed = False
        for d in DIRECTIONS:
            nx, ny = pos[-1][0]+d[0], pos[-1][1]+d[1]
            if (nx, ny) not in occupied:
                pos.append((nx, ny))
                occupied[(nx, ny)] = i
                placed = True
                break
        if not placed:
            # chain trapped – partial fold counts as failure
            return pos, 0, False

    # compute energy
    energy = 0
    for i, (x, y) in enumerate(pos):
        if sequence[i] != 1:
            continue
        for d in DIRECTIONS:
            nb = (x+d[0], y+d[1])
            j = occupied.get(nb, -1)
            if j == -1 or abs(j - i) == 1:
                continue
            if sequence[j] == 1:
                energy -= 1   # H-H contact
    energy //= 2              # each pair counted twice

    success = energy <= ENERGY_GOAL
    return pos, energy, success

def evaluate_seed(seed, length=20):
    rng = random.Random(seed)
    seq = make_sequence(rng, length)
    # run fold with rng-seeded direction shuffle
    random.seed(seed)
    pos, energy, success = fold(seq, rng, ATTEMPTS)
    return {
        "seed": seed,
        "length": length,
        "sequence": seq,
        "energy": energy,
        "success": success,
        "fold_length": len(pos),   # <length means trapped
    }

def child_seed(parent_seed, k):
    return random.Random(parent_seed * 1000 + k).randrange(2**31)

def crossover(seed_a, seed_b, length, rng):
    """Mix sequences from two parents at a random cut-point."""
    seqA = make_sequence(random.Random(seed_a), length)
    seqB = make_sequence(random.Random(seed_b), length)
    cut = rng.randint(1, length - 1)
    child_seq = seqA[:cut] + seqB[cut:]
    return child_seq

def fold_sequence(seq, seed):
    random.seed(seed)
    pos, energy, success = fold(seq, random.Random(seed), ATTEMPTS)
    return {
        "length": len(seq),
        "sequence": seq,
        "energy": energy,
        "success": success,
        "fold_length": len(pos),
    }

# ── main simulation ───────────────────────────────────────────────────────
def run():
    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(exist_ok=True)

    rng_master = random.Random(MASTER_SEED)
    lineage = []

    # Generation 0 – base seeds, one per chain length
    gen0 = []
    for length in CHAIN_LENGTHS:
        seed = rng_master.randrange(2**31)
        r = evaluate_seed(seed, length)
        r["gen"] = 0
        r["parent"] = None
        r["id"] = f"g0-L{length}-s{seed}"
        lineage.append(r)
        gen0.append(r)
        status = "✓ FOLD" if r["success"] else "✗ FAIL"
        print(f"  {status}  g0 L={length:2d}  energy={r['energy']:3d}  "
              f"fold_len={r['fold_length']}/{length}  seed={seed}")

    # Branching generations
    prev_gen = gen0
    for g in range(1, GENERATIONS + 1):
        print(f"\n── generation {g} ──")
        candidates = []
        for parent in prev_gen:
            for k in range(CHILDREN):
                cseed = child_seed(parent["seed"], k)
                r = evaluate_seed(cseed, parent["length"])
                r["gen"] = g
                r["parent"] = parent["id"]
                r["id"] = f"g{g}-L{parent['length']}-s{cseed}"
                candidates.append(r)
                status = "✓ FOLD" if r["success"] else "✗ FAIL"
                print(f"  {status}  L={parent['length']:2d}  "
                      f"energy={r['energy']:3d}  "
                      f"fold_len={r['fold_length']}/{parent['length']}")
            lineage.extend(candidates[-CHILDREN:])

        # Keep best 2 per length (lowest energy)
        best = {}
        for r in candidates:
            L = r["length"]
            if L not in best or r["energy"] < best[L]["energy"]:
                best[L] = r
        # second best
        second = {}
        for r in candidates:
            L = r["length"]
            if r["id"] == best[L]["id"]:
                continue
            if L not in second or r["energy"] < second[L]["energy"]:
                second[L] = r
        prev_gen = list(best.values()) + list(second.values())

    # Cross-branch crossover on final survivors
    print(f"\n── cross-branch crossover ──")
    survivors = prev_gen
    cross_results = []
    for i, a in enumerate(survivors):
        for j, b in enumerate(survivors):
            if i >= j or a["length"] != b["length"]:
                continue
            crng = random.Random(a["seed"] ^ b["seed"])
            seq = crossover(a["seed"], b["seed"], a["length"], crng)
            cseed = crng.randrange(2**31)
            r = fold_sequence(seq, cseed)
            r["gen"] = GENERATIONS + 1
            r["parent"] = f"{a['id']}+{b['id']}"
            r["id"] = f"cross-L{a['length']}-{cseed}"
            cross_results.append(r)
            lineage.append(r)
            status = "✓ FOLD" if r["success"] else "✗ FAIL"
            print(f"  {status}  cross L={a['length']:2d}  "
                  f"energy={r['energy']:3d}  "
                  f"fold_len={r['fold_length']}/{a['length']}")

    # Summary
    total   = len(lineage)
    success = sum(1 for r in lineage if r["success"])
    print(f"\n── summary ──")
    print(f"  total records : {total}")
    print(f"  successful    : {success}  ({100*success//total}%)")
    print(f"  failed        : {total-success}")

    best_all = min(lineage, key=lambda r: r["energy"])
    print(f"  best energy   : {best_all['energy']}  ({best_all['id']})")

    # Save
    out_path = out_dir / "lineage.jsonl"
    with open(out_path, "w") as f:
        for r in lineage:
            json.dump(r, f, ensure_ascii=False)
            f.write("\n")

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    summary = {
        "algo": "fold-sim-0.1",
        "master_seed": MASTER_SEED,
        "chain_lengths": CHAIN_LENGTHS,
        "energy_goal": ENERGY_GOAL,
        "generations": GENERATIONS,
        "children_per_parent": CHILDREN,
        "total": total,
        "successful": success,
        "best_energy": best_all["energy"],
        "best_id": best_all["id"],
        "lineage_sha256": sha,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"\n  lineage sha256: {sha}")
    print(f"  saved → {out_path}")
    return summary

if __name__ == "__main__":
    t0 = time.time()
    s = run()
    print(f"  runtime       : {time.time()-t0:.3f}s")
