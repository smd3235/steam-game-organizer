"""Extracted from tools/review_backups.py.

    diff_backups was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from tools.review_backups import load_json_manifest
from pathlib import Path


def diff_backups(backup1: Path, backup2: Path):
    """Show differences between two backups."""
    m1 = load_json_manifest(backup1)
    m2 = load_json_manifest(backup2)

    if not m1 or not m2:
        print("Error: JSON manifests not found for one or both backups")
        return

    files1 = {f["path"]: f for f in m1.get("files", [])}
    files2 = {f["path"]: f for f in m2.get("files", [])}

    all_paths = set(files1.keys()) | set(files2.keys())

    added = []
    removed = []
    modified = []

    for path in sorted(all_paths):
        f1 = files1.get(path)
        f2 = files2.get(path)

        if f1 and not f2:
            removed.append((path, f1))
        elif f2 and not f1:
            added.append((path, f2))
        elif f1 and f2 and (f1["size"] != f2["size"] or f1.get("modified") != f2.get("modified")):
            modified.append((path, f1, f2))

    print(f"Diff: {backup1.name} -> {backup2.name}\n")

    if added:
        print(f"Added ({len(added)}):")
        for path, f in added[:20]:
            size = f"{f['size']:,} bytes" if not f["is_dir"] else "<dir>"
            print(f"  + {path} ({size})")
        if len(added) > 20:
            print(f"  ... and {len(added) - 20} more")

    if removed:
        print(f"\nRemoved ({len(removed)}):")
        for path, f in removed[:20]:
            size = f"{f['size']:,} bytes" if not f["is_dir"] else "<dir>"
            print(f"  - {path} ({size})")
        if len(removed) > 20:
            print(f"  ... and {len(removed) - 20} more")

    if modified:
        print(f"\nModified ({len(modified)}):")
        for path, f1, f2 in modified[:20]:
            size1 = f"{f1['size']:,}" if not f1["is_dir"] else "<dir>"
            size2 = f"{f2['size']:,}" if not f2["is_dir"] else "<dir>"
            print(f"  ~ {path}: {size1} -> {size2}")
        if len(modified) > 20:
            print(f"  ... and {len(modified) - 20} more")

    if not added and not removed and not modified:
        print("No differences found.")
