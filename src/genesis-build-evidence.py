import csv
import os
import re
import json
import time
import hashlib
import sqlite3
from pathlib import Path
from collections import Counter

HOME = Path.home().resolve()
REPORT = HOME / "downloads/genesis_discovery_20261116_051557.tsv"

if not REPORT.is_file():
    raise SystemExit("STOP: discovery report not found")

STAMP = time.strftime("%Y%m%d_%H%M%S")
OUT = HOME / "downloads" / f"genesis_evidence_{STAMP}"
OUT.mkdir(parents=False, exist_ok=False)

DB = OUT / "evidence.sqlite"
SUMMARY = OUT / "summary.json"
CSV_OUT = OUT / "artifacts.tsv"

MAX_HASH_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024

TEXT_EXT = {
    ".py", ".sh", ".zsh", ".bash", ".md", ".txt",
    ".json", ".yaml", ".yml", ".toml", ".ini",
    ".conf", ".sql", ".csv", ".tsv", ".xml",
    ".service", ".log"
}

SKIP_NAMES = {
    ".env", ".env.local", "id_rsa", "id_ed25519",
    "credentials", "secrets.json"
}

# ตรวจจับเฉพาะรูปแบบ ไม่เก็บค่าความลับ
SECRET_PATTERNS = {
    "AWS_ACCESS_KEY_PATTERN":
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "PRIVATE_KEY_HEADER":
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "TOKEN_ASSIGNMENT":
        re.compile(
            r"(?i)\b(?:token|api_key|secret_access_key|password)"
            r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"
        ),
}

ROLE_RULES = [
    ("MAPPING", re.compile(
        r"mapping|master-map|topology|semantic-inventory|"
        r"discovery-home|execution-map", re.I)),
    ("REGISTRY", re.compile(
        r"registry|catalog|identity|relations|lineage", re.I)),
    ("BLUEPRINT", re.compile(
        r"blueprint|architecture|design|contract|specification", re.I)),
    ("TEST", re.compile(
        r"(^|[/_.-])test|simulation|benchmark|scenario|fault", re.I)),
    ("RUNTIME_RECORD", re.compile(
        r"runtime|execution|processing|worker|daemon|outbox", re.I)),
    ("RECOVERY", re.compile(
        r"recover|restore|reconcile|rollback|checkpoint|vault", re.I)),
    ("INTEGRITY", re.compile(
        r"hash|checksum|manifest|integrity|signature|duplicate", re.I)),
    ("SOURCE_CODE", re.compile(
        r"\.(py|sh|zsh|bash)$", re.I)),
    ("DOCUMENTATION", re.compile(
        r"\.(md|txt)$", re.I)),
    ("STRUCTURED_DATA", re.compile(
        r"\.(json|yaml|yml|toml|ini|csv|tsv|sql)$", re.I)),
]

def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def safe_text(path):
    if path.suffix.lower() not in TEXT_EXT:
        return None
    if path.stat().st_size > MAX_TEXT_BYTES:
        return None
    data = path.read_bytes()
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="replace")

def classify(path):
    s = str(path).lower()
    roles = [name for name, rx in ROLE_RULES if rx.search(s)]
    if not roles:
        roles = ["UNCLASSIFIED"]
    return roles

# อ่านรายการผู้สมัคร
candidates = []
with REPORT.open(encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        p = Path(row["path"])
        try:
            resolved = p.resolve(strict=True)
            resolved.relative_to(HOME)
        except (OSError, ValueError):
            continue

        if p.is_symlink() or not p.is_file():
            continue
        if p.name.lower() in SKIP_NAMES or p.name.lower().startswith(".env"):
            continue

        candidates.append((p, row))

con = sqlite3.connect(DB)
con.execute("PRAGMA journal_mode=WAL")
con.execute("PRAGMA foreign_keys=ON")

con.executescript("""
CREATE TABLE run (
    run_id TEXT PRIMARY KEY,
    created_at TEXT,
    source_report TEXT,
    scope TEXT,
    execution_policy TEXT
);

CREATE TABLE artifacts (
    artifact_id INTEGER PRIMARY KEY,
    path TEXT UNIQUE,
    source_root TEXT,
    extension TEXT,
    size_bytes INTEGER,
    mtime_epoch INTEGER,
    sha256 TEXT,
    hash_status TEXT,
    read_status TEXT,
    primary_role TEXT,
    evidence_level TEXT,
    notes TEXT
);

CREATE TABLE categories (
    artifact_id INTEGER,
    category TEXT,
    match_type TEXT,
    PRIMARY KEY (artifact_id, category),
    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id)
);

CREATE TABLE signals (
    artifact_id INTEGER,
    signal TEXT,
    count INTEGER,
    PRIMARY KEY (artifact_id, signal),
    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id)
);

CREATE TABLE references_found (
    source_artifact_id INTEGER,
    target_artifact_id INTEGER,
    relation TEXT,
    reference_text TEXT,
    PRIMARY KEY (
        source_artifact_id, target_artifact_id,
        relation, reference_text
    ),
    FOREIGN KEY (source_artifact_id) REFERENCES artifacts(artifact_id),
    FOREIGN KEY (target_artifact_id) REFERENCES artifacts(artifact_id)
);

CREATE INDEX idx_artifact_role ON artifacts(primary_role);
CREATE INDEX idx_artifact_hash ON artifacts(sha256);
CREATE INDEX idx_category ON categories(category);
""")

RUN_ID = "EVIDENCE-" + STAMP

con.execute("""
INSERT INTO run VALUES (?, ?, ?, ?, ?)
""", (
    RUN_ID,
    time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    str(REPORT),
    "Candidate files under supplied discovery roots",
    "READ_ONLY_SOURCE; NO_SCRIPT_EXECUTION; NO_NETWORK"
))

# สร้าง path index สำหรับตรวจการอ้างถึงไฟล์แบบตรงตัว
path_to_id = {}
pending_refs = []
counts = Counter()
role_counts = Counter()
category_counts = Counter()
secret_counts = Counter()

for p, row in candidates:
    try:
        st = p.stat()
        size = st.st_size
        mtime = int(st.st_mtime)
    except OSError:
        counts["STAT_ERROR"] += 1
        continue

    roles = classify(p)
    primary_role = roles[0]

    digest = None
    hash_status = "SKIPPED_SIZE_LIMIT"
    if size <= MAX_HASH_BYTES:
        try:
            digest = sha256_file(p)
            hash_status = "HASHED"
        except OSError:
            hash_status = "HASH_ERROR"

    text = None
    read_status = "NOT_TEXT_OR_SIZE_LIMIT"
    if size <= MAX_TEXT_BYTES:
        try:
            text = safe_text(p)
            if text is not None:
                read_status = "READ"
            elif p.suffix.lower() in TEXT_EXT:
                read_status = "BINARY_OR_UNREADABLE"
        except (OSError, UnicodeError):
            read_status = "READ_ERROR"

    # ระดับนี้เป็นเพียงระดับการมีข้อมูล ไม่ใช่การรับรองความถูกต้อง
    if read_status == "READ":
        if p.suffix.lower() == ".log" or "runtime" in str(p).lower():
            evidence_level = "E2_RECORDED_TRACE_CANDIDATE"
        elif primary_role == "TEST":
            evidence_level = "E1_TEST_OR_SCENARIO"
        else:
            evidence_level = "E1_STATIC_CONTENT"
    else:
        evidence_level = "E0_INVENTORY_ONLY"

    cur = con.execute("""
        INSERT INTO artifacts (
            path, source_root, extension, size_bytes, mtime_epoch,
            sha256, hash_status, read_status, primary_role,
            evidence_level, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(p), row["source_root"], p.suffix.lower() or "[none]",
        size, mtime, digest, hash_status, read_status,
        primary_role, evidence_level,
        "Classification is heuristic; execution is not verified."
    ))
    aid = cur.lastrowid
    path_to_id[str(p)] = aid

    for role in roles:
        role_counts[role] += 1

    cats = set(row.get("categories", "").split(","))
    for cat in sorted(c for c in cats if c):
        con.execute("""
            INSERT OR IGNORE INTO categories
            VALUES (?, ?, ?)
        """, (aid, cat, row.get("match_type", "UNKNOWN")))
        category_counts[cat] += 1

    if text is not None:
        for name, rx in SECRET_PATTERNS.items():
            n = len(rx.findall(text))
            if n:
                con.execute(
                    "INSERT INTO signals VALUES (?, ?, ?)",
                    (aid, name, n)
                )
                secret_counts[name] += n

        # เก็บเฉพาะการอ้างถึง absolute path ใน HOME
        # ไม่เก็บบรรทัดต้นฉบับหรือค่าความลับ
        for match in re.findall(
            r"/data/data/com\.termux/files/home/[A-Za-z0-9_./@+-]+",
            text
        ):
            target = str(Path(match))
            if target != str(p):
                pending_refs.append((aid, target))

    counts["ARTIFACTS"] += 1
    counts[hash_status] += 1
    counts[read_status] += 1
    counts[evidence_level] += 1

# เชื่อมเฉพาะ path ที่ตรงกับรายการผู้สมัครแบบ exact match
for source_id, target_path in pending_refs:
    target_id = path_to_id.get(target_path)
    if target_id is not None:
        con.execute("""
            INSERT OR IGNORE INTO references_found
            VALUES (?, ?, ?, ?)
        """, (
            source_id, target_id,
            "LITERAL_ABSOLUTE_PATH_REFERENCE",
            target_path
        ))

con.commit()

# สรุปข้อมูลจากฐานข้อมูลจริง
db_roles = dict(con.execute("""
    SELECT primary_role, COUNT(*)
    FROM artifacts GROUP BY primary_role ORDER BY primary_role
"""))

db_evidence = dict(con.execute("""
    SELECT evidence_level, COUNT(*)
    FROM artifacts GROUP BY evidence_level ORDER BY evidence_level
"""))

ref_count = con.execute(
    "SELECT COUNT(*) FROM references_found"
).fetchone()[0]

artifact_count = con.execute(
    "SELECT COUNT(*) FROM artifacts"
).fetchone()[0]

# TSV สำหรับเปิดดูรายการโดยไม่ต้อง query SQLite
with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow([
        "artifact_id", "role", "evidence_level",
        "size_bytes", "sha256", "hash_status", "path"
    ])
    for r in con.execute("""
        SELECT artifact_id, primary_role, evidence_level,
               size_bytes, sha256, hash_status, path
        FROM artifacts ORDER BY primary_role, path
    """):
        w.writerow(r)

summary = {
    "run_id": RUN_ID,
    "database": str(DB),
    "artifact_table": str(CSV_OUT),
    "source_report": str(REPORT),
    "artifacts": artifact_count,
    "references_exact_match": ref_count,
    "role_counts": db_roles,
    "evidence_level_counts": db_evidence,
    "secret_pattern_counts": dict(secret_counts),
    "limitations": [
        "Filename/content keyword matches are not proof of function.",
        "Literal path references are not proof of runtime dependency.",
        "Recorded traces are not proof of successful execution.",
        "No script was executed and no network was used.",
        "Files over configured limits may not have been read or hashed."
    ]
}

SUMMARY.write_text(
    json.dumps(summary, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

con.close()

print("=== GENESIS EVIDENCE REGISTRY ===")
print("RUN_ID:", RUN_ID)
print("DATABASE:", DB)
print("ARTIFACTS_TSV:", CSV_OUT)
print("SUMMARY:", SUMMARY)
print("ARTIFACTS:", artifact_count)
print("EXACT_PATH_REFERENCES:", ref_count)

print("\n=== ROLE COUNTS ===")
for k, v in sorted(db_roles.items()):
    print(k, v)

print("\n=== EVIDENCE LEVELS ===")
for k, v in sorted(db_evidence.items()):
    print(k, v)

print("\n=== SECRET PATTERN COUNTS (NO VALUES STORED) ===")
print(dict(secret_counts))

print("\nSOURCE_FILES_MODIFIED=NO")
print("SOURCE_SCRIPTS_EXECUTED=NO")
print("NETWORK_USED=NO")
print("DATABASE_CREATED=YES")
