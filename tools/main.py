"""Extracted from tools/review_backups.py.

    main was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import argparse
from tools.diff_backups import diff_backups
from tools.review_backups import interactive_mode
from tools.review_backups import list_backups
from tools.review_backups import print_backup_summary
from tools.review_backups import show_stats
from tools.review_backups import verify_backups
from tools.search_backups import search_backups


def main():
    parser = argparse.ArgumentParser(description="Review Steam Game Organizer backups")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("-s", "--search", help="Search all backups for pattern")
    parser.add_argument("-d", "--diff", nargs=2, help="Diff two backups by index (1=latest)")
    parser.add_argument("-v", "--verify", action="store_true", help="Verify all backup integrity")
    parser.add_argument("--stats", action="store_true", help="Show backup statistics")
    parser.add_argument("-t", "--type", choices=["all", "file", "dir"], default="all", help="File type filter for search")
    parser.add_argument("--min-size", type=int, default=0, help="Minimum file size for search")
    parser.add_argument("--max-size", type=int, help="Maximum file size for search")
    args = parser.parse_args()

    backups = list_backups()
    if not backups:
        print("No backups found in backup/")
        return 1

    if args.interactive:
        interactive_mode()
        return 0

    if args.search:
        search_backups(args.search, args.type, args.min_size, args.max_size)
        return 0

    if args.diff:
        try:
            idx1 = int(args.diff[0]) - 1
            idx2 = int(args.diff[1]) - 1
            if 0 <= idx1 < len(backups) and 0 <= idx2 < len(backups):
                diff_backups(backups[idx1], backups[idx2])
            else:
                print(f"Invalid backup index (1-{len(backups)})")
        except ValueError:
            print("Backup indices must be numbers")
        return 0

    if args.verify:
        verify_backups()
        return 0

    if args.stats:
        show_stats()
        return 0

    # Default: show summary
    print_backup_summary()
    return 0
