#!/usr/bin/env python3
"""
Diary "load everything" bundle builder (v2 — summary-aware).

Assembles Diary's full working context into a few large chunk files so it loads
in a handful of `cat` reads instead of ~271 individual model-mediated reads.

Load scheme (fits the 1M window):
  1. Frames (5 files)                          — full, always
  2. Parts (Parts Map + Parts/*)               — full, always
  3. Insights (Log, Intentions, Speaking + /*) — full, always
  4. People (2. Useful/People/**)              — full, always
  5. Monthly SUMMARIES ("4. AI/Summaries by months/*.md") — for every month
     that has one (old months, compressed)
  6. FULL sessions + daily notes, interleaved by date, ONLY for months that do NOT
     yet have a summary (the current/in-progress month, e.g. July). As each month is
     summarized (via the diary-monthly-summary skill), it moves from block 6 -> 5.

Read via EXEC `cat` (NOT the read tool — read caps at 128KB; cat delivers the full
chunk under the 300k toolResultMaxChars cap).

Run: python3 scripts/diary-context-bundle.py
Output: /path/to/bundle-output/chunk-NN.md  +  MANIFEST.txt
"""
import os, re, glob

VAULT = "/path/to/Diary"
OUT   = "/path/to/bundle-output"
SUMDIR = os.path.join(VAULT, "4. AI/Summaries by months")
CHUNK_MAX = 250000  # chars/chunk, safely under contextLimits.toolResultMaxChars (300000)

def rel(p):  return os.path.relpath(p, VAULT)
def read(p):
    try:
        with open(p, encoding="utf-8") as f: return f.read()
    except Exception as e:
        return f"[[bundle: could not read {rel(p)}: {e}]]"

ordered = []  # (relpath, content) in final load order
date_re = re.compile(r"(\d{4})-(\d{2})-\d{2}")

# --- Block 1: Frames ---
for f in ["agents.md",
          "World & self model/My world & self model.md",
          "My zones mindmap.md",
          "My relationship model.md",
          "2. Useful/Personal values 2021.md"]:
    p = os.path.join(VAULT, f)
    if os.path.isfile(p): ordered.append((f, read(p)))

# --- Block 2: Parts ---
pm = os.path.join(VAULT, "4. AI/Parts Map.md")
if os.path.isfile(pm): ordered.append((rel(pm), read(pm)))
parts_dir = os.path.join(VAULT, "4. AI/Parts")
seen = set()
for f in ["README.md", "Overview.md", "Shadow Map.md"]:
    p = os.path.join(parts_dir, f)
    if os.path.isfile(p): ordered.append((rel(p), read(p))); seen.add(f)
for p in sorted(glob.glob(os.path.join(parts_dir, "*.md"))):
    if os.path.basename(p) not in seen: ordered.append((rel(p), read(p)))

# --- Block 3: Insights ---
for f in ["4. AI/Insights Log.md",
          "4. AI/Intentions.md",
          "4. AI/Speaking My Truth - Framework.md"]:
    p = os.path.join(VAULT, f)
    if os.path.isfile(p): ordered.append((f, read(p)))
for p in sorted(glob.glob(os.path.join(VAULT, "4. AI/Insights", "*.md"))):
    ordered.append((rel(p), read(p)))

# --- Block 4: People ---
for p in sorted(glob.glob(os.path.join(VAULT, "2. Useful/People", "**", "*.md"), recursive=True)):
    ordered.append((rel(p), read(p)))

# --- Window: full raw text for the last INCOMPLETE (current) month + the last COMPLETE
#     month; monthly summaries only for months OLDER than that (even if June has a summary,
#     it loads full while it is still the last complete month). ---
import datetime
_today = datetime.date.today()
_cur = _today.strftime("%Y-%m")
_prev = (_today.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
FULL_MONTHS = {_cur, _prev}     # e.g. {"2026-07", "2026-06"}

def month_of(path):
    m = date_re.search(os.path.basename(path))
    return f"{m.group(1)}-{m.group(2)}" if m else "9999-99"

# --- Block 5: Monthly summaries — only for months OLDER than the full-text window ---
summary_months = set()   # months that HAVE a summary file
for p in sorted(glob.glob(os.path.join(SUMDIR, "*.md"))):
    m = re.match(r"(\d{4}-\d{2})", os.path.basename(p))
    mon = m.group(1) if m else None
    if mon: summary_months.add(mon)
    if mon in FULL_MONTHS:            # last complete/current month -> loaded full below, skip its summary
        continue
    ordered.append((rel(p), read(p)))

# --- Block 6: FULL sessions + daily, interleaved by date, for months in FULL_MONTHS
#     (last complete + current) OR any month lacking a summary (fallback). ---
def load_full(path):
    mon = month_of(path)
    return mon in FULL_MONTHS or mon not in summary_months

dated = []  # (date, tag, relpath, content)  tag 0=session (first), 1=daily
for g in ["3. Completed/Sessions/*.md",
          "4. AI/Session Notes/*.md",
          "3. Completed/Sessions Secondary/*.md",
          "3. Completed/Rituals*.md"]:
    for p in glob.glob(os.path.join(VAULT, g)):
        if not load_full(p): continue
        d = date_re.search(os.path.basename(p))
        dated.append((d.group(0) if d else "9999-99-99", 0, rel(p), read(p)))
for p in glob.glob(os.path.join(VAULT, "0. Daily Notes", "*.md")):
    if not load_full(p): continue
    d = date_re.search(os.path.basename(p))
    dated.append((d.group(0) if d else "9999-99-99", 1, rel(p), read(p)))
for d, tag, rp, c in sorted(dated, key=lambda x: (x[0], x[1], x[2])):
    ordered.append((rp, c))

# --- Write chunks at file boundaries ---
os.makedirs(OUT, exist_ok=True)
for old in glob.glob(os.path.join(OUT, "chunk-*.md")): os.remove(old)
chunks, cur, cur_len, manifest = [], [], 0, []
for rp, content in ordered:
    block = f"\n\n===== FILE: {rp} =====\n\n{content}"
    if cur and cur_len + len(block) > CHUNK_MAX:
        chunks.append("".join(cur)); cur, cur_len = [], 0
    cur.append(block); cur_len += len(block); manifest.append(rp)
if cur: chunks.append("".join(cur))

paths = []
for i, ch in enumerate(chunks, 1):
    fn = os.path.join(OUT, f"chunk-{i:02d}.md")
    with open(fn, "w", encoding="utf-8") as f: f.write(ch)
    paths.append(fn)

total_chars = sum(len(c) for c in chunks)
loaded_summary_months = sorted(summary_months - FULL_MONTHS)
with open(os.path.join(OUT, "MANIFEST.txt"), "w", encoding="utf-8") as f:
    f.write(f"Diary context bundle: {len(ordered)} files, {len(chunks)} chunks, {total_chars} chars\n")
    f.write(f"Loaded as summaries (compressed): {', '.join(loaded_summary_months) or '(none)'}\n")
    f.write(f"Loaded FULL (last complete + current month): {', '.join(sorted(FULL_MONTHS))}\n")
    f.write("READ THESE CHUNKS IN ORDER via exec `cat` (one per turn):\n")
    for p in paths: f.write(f"  {p}  ({len(open(p, encoding='utf-8').read())} chars)\n")
    f.write("\nFULL FILE ORDER:\n")
    for rp in manifest: f.write(f"  {rp}\n")

print(f"Bundle: {len(ordered)} files -> {len(chunks)} chunks, {total_chars} chars (~{total_chars//16*10//1000}k tokens)")
print(f"Loaded as summaries: {', '.join(loaded_summary_months) or '(none)'}")
print(f"Loaded FULL (last complete + current): {', '.join(sorted(FULL_MONTHS))}")
for p in paths: print(f"  {os.path.basename(p)}  {len(open(p, encoding='utf-8').read())} chars")
print(f"Manifest: {os.path.join(OUT,'MANIFEST.txt')}")
