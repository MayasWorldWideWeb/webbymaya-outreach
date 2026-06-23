#!/usr/bin/env python3
"""
fix_prospects.py — One-time + ongoing cleanup of prospect CSV files.
Applies correct category normalization to all existing CSVs,
unifies aliases, and flags junk records for removal.

Usage:
  python3 fix_prospects.py              # fix all CSVs
  python3 fix_prospects.py --dry-run    # preview changes only
  python3 fix_prospects.py --report     # print mismatch report only
"""
import argparse, csv, importlib.util, sys
from pathlib import Path
from collections import Counter, defaultdict

SCRIPT_DIR = Path(__file__).parent

# ── Load normalize_category from batch_send_outreach ─────────────────────────
def _load_normalizer():
    spec = importlib.util.spec_from_file_location("bso", SCRIPT_DIR / "batch_send_outreach.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize_category, mod._SKIP_CATEGORIES, mod._CATEGORY_ALIASES

try:
    normalize_category, SKIP_CATEGORIES, CATEGORY_ALIASES = _load_normalizer()
except Exception as e:
    sys.exit(f"Could not load batch_send_outreach: {e}")

# ── Junk-name filters — records we should drop entirely ──────────────────────
_JUNK_KEYWORDS = [
    # Chain restaurants / fast food — they have websites
    "mcdonald", "burger king", "wendy's", "taco bell", "subway ", "chick-fil",
    "dunkin", "starbucks", "domino", "little caesar", "papa john", "pizza hut",
    "popeye", "kfc ", "chipotle", "panera", "five guys", "wawa", "sheetz",
    "wingstop", "raising cane", "jersey mike", "jimmy john",
    # Government / institutions
    "philadelphia department", "city of ", "county of ", "school district",
    "fire station", "police station", "post office",
    # Landlord / real estate listings (not businesses)
    "apartments", "apartment complex", "rental property",
    # Auto tags — not website clients
    "auto tag", "auto tags", "notary tag",
]

def _is_junk(name: str, category: str) -> bool:
    n = (name or "").lower()
    return any(kw in n for kw in _JUNK_KEYWORDS)

def _should_skip_cat(category: str) -> bool:
    return category in SKIP_CATEGORIES


def fix_file(path: Path, dry_run: bool = False) -> dict:
    """Fix one CSV. Returns stats dict."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        return {"file": path.name, "total": 0, "fixed": 0, "removed": 0}

    fixed_rows  = []
    n_fixed     = 0
    n_removed   = 0
    changes     = []

    for row in rows:
        name     = row.get("name", "").strip()
        old_cat  = row.get("category", "").strip()

        # Drop junk
        if _is_junk(name, old_cat):
            n_removed += 1
            changes.append(("REMOVE", name, old_cat, "junk/chain"))
            continue

        # Normalize category
        new_cat = normalize_category(name, old_cat)

        # Unify aliases (mechanic → auto repair etc.)
        if new_cat.lower() in CATEGORY_ALIASES:
            alias = CATEGORY_ALIASES[new_cat.lower()]
            if alias:
                new_cat = alias

        # Drop skip-categories
        if _should_skip_cat(new_cat):
            n_removed += 1
            changes.append(("REMOVE", name, old_cat, f"skip-cat:{new_cat}"))
            continue

        if new_cat != old_cat:
            n_fixed += 1
            changes.append(("FIX", name, old_cat, new_cat))
            row["category"] = new_cat

        fixed_rows.append(row)

    if not dry_run and (n_fixed > 0 or n_removed > 0):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(fixed_rows)

    return {
        "file":    path.name,
        "total":   len(rows),
        "kept":    len(fixed_rows),
        "fixed":   n_fixed,
        "removed": n_removed,
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",  action="store_true", help="Preview only — don't write")
    parser.add_argument("--report",   action="store_true", help="Print mismatch report then exit")
    parser.add_argument("--verbose",  action="store_true", help="Show every change")
    args = parser.parse_args()

    csvs = sorted(SCRIPT_DIR.glob("prospects_*.csv"))
    if not csvs:
        print("No prospect CSVs found.")
        return

    if args.report:
        # Just show what's wrong without fixing
        print(f"\n{'='*65}")
        print(f"  Category Mismatch Report — {len(csvs)} files")
        print(f"{'='*65}\n")
        all_changes = defaultdict(list)
        for path in csvs:
            result = fix_file(path, dry_run=True)
            for action, name, old, new in result["changes"]:
                all_changes[action].append((name, old, new, path.name))

        print(f"FIXES needed ({len(all_changes['FIX'])}):")
        for name, old, new, fname in all_changes["FIX"][:50]:
            print(f"  [{old}] → [{new}]  \"{name}\"  ({fname})")
        if len(all_changes["FIX"]) > 50:
            print(f"  ... and {len(all_changes['FIX'])-50} more")

        print(f"\nREMOVALS ({len(all_changes['REMOVE'])}):")
        for name, old, new, fname in all_changes["REMOVE"][:30]:
            print(f"  [{new}]  \"{name}\"  ({fname})")
        return

    label = "DRY RUN — " if args.dry_run else ""
    print(f"\n{'='*65}")
    print(f"  {label}WebByMaya Prospect Cleanup — {len(csvs)} files")
    print(f"{'='*65}\n")

    total_fixed   = 0
    total_removed = 0
    total_records = 0

    for path in csvs:
        result = fix_file(path, dry_run=args.dry_run)
        total_fixed   += result["fixed"]
        total_removed += result["removed"]
        total_records += result["total"]

        if result["fixed"] or result["removed"]:
            marker = "→" if not args.dry_run else "~"
            print(f"  {marker} {result['file']}")
            print(f"      {result['total']} total  |  "
                  f"{result['fixed']} re-categorized  |  "
                  f"{result['removed']} removed")
            if args.verbose:
                for action, name, old, new in result["changes"][:20]:
                    print(f"        [{action}] \"{name}\"  {old} → {new}")
        else:
            print(f"  ✓ {result['file']} — clean")

    print(f"\n{'='*65}")
    print(f"  Records scanned : {total_records:,}")
    print(f"  Re-categorized  : {total_fixed:,}")
    print(f"  Removed (junk)  : {total_removed:,}")
    if args.dry_run:
        print(f"\n  (Dry run — no files were changed. Remove --dry-run to apply.)")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
