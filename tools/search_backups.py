"""Extracted from tools/review_backups.py.

    search_backups was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""


from tools.review_backups import list_backups
from tools.review_backups import load_json_manifest
def search_backups(pattern: str, file_type: str = "all", min_size: int = 0, max_size: int = None):
    """Search all backups for files matching pattern."""
    backups = list_backups()
    pattern_lower = pattern.lower()
    results = []

    for backup in backups:
        manifest = load_json_manifest(backup)
        if not manifest:
            continue

        for file_info in manifest.get("files", []):
            if file_info["is_dir"] and file_type != "all" and file_type != "dir":
                continue
            if not file_info["is_dir"] and file_type != "all" and file_type != "file":
                continue
            if file_info["size"] < min_size:
                continue
            if max_size and file_info["size"] > max_size:
                continue
            if pattern_lower in file_info["path"].lower():
                results.append((backup, manifest, file_info))

    if not results:
        print(f"No matches for '{pattern}'")
        return

    print(f"Found {len(results)} match(es) for '{pattern}':\n")

    # Group by backup
    by_backup = {}
    for backup, manifest, file_info in results:
        if backup not in by_backup:
            by_backup[backup] = {"manifest": manifest, "files": []}
        by_backup[backup]["files"].append(file_info)

    for backup, data in by_backup.items():
        m = data["manifest"]
        date = m.get("created", "")[:19].replace("T", " ")
        print(f"\n  {backup.name} ({date})")
        for f in sorted(data["files"], key=lambda x: x["path"]):
            size_str = f"{f['size']:,} bytes" if not f["is_dir"] else "<dir>"
            print(f"    {f['path']} ({size_str})")
