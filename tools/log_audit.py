#!/usr/bin/env python3
"""
Log audit tool for Steam Game Organizer.

Scans the logs/ directory for error patterns, repeated warnings, log rotation
issues, and other anomalies. Useful after a run to spot issues that only
appear in logs (e.g., 7z extraction failures, Python tracebacks, repeated
artwork download failures).

    python tools\\log_audit.py                 # audit all logs in logs/
    python tools\\log_audit.py --since 2026-11-20   # only logs from that date onward
    python tools\\log_audit.py --level WARN     # only show WARN and above
    python tools\\log_audit.py --report json    # write JSON report to stdout
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# Patterns that indicate real problems in logs
ERROR_PATTERNS = [
    (re.compile(r"Traceback", re.IGNORECASE), "Python traceback"),
    (re.compile(r"raise SystemExit", re.IGNORECASE), "SystemExit raised"),
    (re.compile(r"FileNotFoundError", re.IGNORECASE), "File not found"),
    (re.compile(r"ModuleNotFoundError", re.IGNORECASE), "Module not found"),
    (re.compile(r"PermissionError", re.IGNORECASE), "Permission denied"),
    (re.compile(r"KeyError", re.IGNORECASE), "KeyError"),
    (re.compile(r"IndexError", re.IGNORECASE), "IndexError"),
    (re.compile(r"TypeError", re.IGNORECASE), "TypeError"),
    (re.compile(r"ValueError", re.IGNORECASE), "ValueError"),
    (re.compile(r"AttributeError", re.IGNORECASE), "AttributeError"),
    (re.compile(r"ImportError", re.IGNORECASE), "Import error"),
    (re.compile(r"OSError", re.IGNORECASE), "OS error"),
    (re.compile(r"RuntimeError", re.IGNORECASE), "Runtime error"),
    (re.compile(r"TclError", re.IGNORECASE), "Tcl/Tk error"),
    (re.compile(r"HTTPError", re.IGNORECASE), "HTTP error"),
    (re.compile(r"unhandled exception", re.IGNORECASE), "Unhandled exception"),
    (re.compile(r"fatal error", re.IGNORECASE), "Fatal error"),
    (re.compile(r"application error", re.IGNORECASE), "Application error"),
]

# Patterns that indicate warnings worth watching
WARN_PATTERNS = [
    (re.compile(r"PRIMARY_UNAVAILABLE", re.IGNORECASE), "Artwork primary unavailable"),
    (re.compile(r"ASSET_FAILED", re.IGNORECASE), "Artwork asset download failed"),
    (re.compile(r"STEAMGRIDDB_FAILED", re.IGNORECASE), "SteamGridDB lookup failed"),
    (re.compile(r"SOURCE_404", re.IGNORECASE), "404 on artwork source"),
    (re.compile(r"ARCHIVE_APPID_MISMATCH", re.IGNORECASE), "Archive appid mismatch"),
    (re.compile(r"TAGS_UNAVAILABLE", re.IGNORECASE), "Steam tags unavailable"),
    (re.compile(r"LOOKUP_NO_ITEMS", re.IGNORECASE), "Steam lookup returned no items"),
    (re.compile(r"RETRY_LOOKUP", re.IGNORECASE), "Steam lookup retry"),
]

# Log line format: 2026-11-20 10:07:59-0700 [INFO ] [COMPONENT] [CORRELATION] MESSAGE
LOG_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[-+]\d{4}) "
    r"\[(?P<level>\w+)\] "
    r"\[(?P<component>[^\]]+)\] "
    r"(?:\[(?P<correlation>[^\]]+)\] )?"
    r"(?P<message>.*)$"
)


class LogResult:
    def __init__(self, path: Path):
        self.path = path
        self.lines: list[dict] = []
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.error_pattern_counts: Counter = Counter()
        self.warn_pattern_counts: Counter = Counter()


def parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse a log timestamp like '2026-11-20 10:07:59-0700'."""
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S%z")
    except ValueError:
        return None


def audit_log(path: Path, since: Optional[datetime] = None, min_level: str = "DEBUG") -> LogResult:
    """Audit a single log file for errors, warnings, and patterns."""
    result = LogResult(path)
    level_order = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
    min_order = level_order.get(min_level.upper(), 0)

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n\r")
                match = LOG_LINE.match(line)
                if not match:
                    continue

                ts = parse_timestamp(match.group("ts"))
                if since is not None and ts is not None and ts < since:
                    continue

                level = match.group("level") or "INFO"
                component = match.group("component") or ""
                message = match.group("message") or ""
                correlation = match.group("correlation") or ""

                entry = {
                    "timestamp": ts.isoformat() if ts else None,
                    "level": level,
                    "component": component,
                    "correlation": correlation,
                    "message": message,
                }
                result.lines.append(entry)

                level_order_val = level_order.get(level.upper(), 0)
                if level_order_val >= min_order:
                    # Check error patterns
                    for pattern, label in ERROR_PATTERNS:
                        if pattern.search(message):
                            result.errors.append(entry)
                            result.error_pattern_counts[label] += 1
                            break  # count once per line

                    # Check warning patterns
                    for pattern, label in WARN_PATTERNS:
                        if pattern.search(message):
                            result.warnings.append(entry)
                            result.warn_pattern_counts[label] += 1
                            break
    except Exception as exc:
        result.errors.append({"error": f"Cannot read log file: {exc}"})

    return result


def audit_logs(
    log_dir: Path = LOG_DIR,
    since: Optional[datetime] = None,
    min_level: str = "DEBUG",
) -> list[LogResult]:
    """Audit all log files in log_dir."""
    results: list[LogResult] = []
    if not log_dir.is_dir():
        return results

    for log_file in sorted(log_dir.glob("*.log")):
        results.append(audit_log(log_file, since=since, min_level=min_level))
    return results


def format_report(results: list[LogResult], json_output: bool = False) -> str:
    """Format audit results as text or JSON."""
    if json_output:
        report = {
            "files_audited": len(results),
            "total_lines": sum(len(r.lines) for r in results),
            "total_errors": sum(len(r.errors) for r in results),
            "total_warnings": sum(len(r.warnings) for r in results),
            "error_pattern_counts": {k: v for k, v in sum(
                (Counter({k: v}) for r in results for k, v in r.error_pattern_counts.items()), Counter()
            ).items()},
            "warn_pattern_counts": {k: v for k, v in sum(
                (Counter({k: v}) for r in results for k, v in r.warn_pattern_counts.items()), Counter()
            ).items()},
            "files": [
                {
                    "path": str(r.path),
                    "lines": len(r.lines),
                    "errors": len(r.errors),
                    "warnings": len(r.warnings),
                    "error_patterns": dict(r.error_pattern_counts),
                    "warn_patterns": dict(r.warn_pattern_counts),
                    "error_entries": r.errors[:10],
                    "warn_entries": r.warnings[:10],
                }
                for r in results
            ],
        }
        return json.dumps(report, indent=2)

    lines: list[str] = []
    lines.append(f"Files audited: {len(results)}")
    lines.append(f"Total log lines: {sum(len(r.lines) for r in results)}")
    lines.append(f"Total errors: {sum(len(r.errors) for r in results)}")
    lines.append(f"Total warnings: {sum(len(r.warnings) for r in results)}")

    total_errors_patterns: Counter = Counter()
    total_warn_patterns: Counter = Counter()
    for r in results:
        total_errors_patterns.update(r.error_pattern_counts)
        total_warn_patterns.update(r.warn_pattern_counts)

    if total_errors_patterns:
        lines.append("\nError patterns:")
        for pattern, count in total_errors_patterns.most_common():
            lines.append(f"  {count:5d}  {pattern}")

    if total_warn_patterns:
        lines.append("\nWarning patterns:")
        for pattern, count in total_warn_patterns.most_common():
            lines.append(f"  {count:5d}  {pattern}")

    lines.append("\nPer-file summary:")
    for r in results:
        status = "OK"
        if r.errors:
            status = "ERRORS"
        elif r.warnings:
            status = "WARNINGS"
        lines.append(
            f"  {r.path.name:<40} lines={len(r.lines):6d} "
            f"errors={len(r.errors):5d} warnings={len(r.warnings):5d}  {status}"
        )
        for err in r.errors[:3]:
            msg = err.get("message", err.get("error", ""))[:80]
            lines.append(f"    ERROR: {msg}")
        for warn in r.warnings[:3]:
            lines.append(f"    WARN:  {warn.get('message', '')[:80]}")

    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Audit Steam Game Organizer log files")
    parser.add_argument("--log-dir", default=str(LOG_DIR), help="logs directory to audit")
    parser.add_argument("--since", help="only show logs from this date (YYYY-MM-DD)")
    parser.add_argument("--level", default="DEBUG", choices=["DEBUG", "INFO", "WARN", "ERROR"],
                        help="minimum log level to report")
    parser.add_argument("--report", choices=["text", "json"], default="text",
                        help="output format")
    args = parser.parse_args()

    since = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"Invalid --since date: {args.since} (expected YYYY-MM-DD)", file=sys.stderr)
            return 1

    log_dir = Path(args.log_dir)
    results = audit_logs(log_dir=log_dir, since=since, min_level=args.level)

    print(format_report(results, json_output=(args.report == "json")))

    total_errors = sum(len(r.errors) for r in results)
    if total_errors > 0:
        print(f"\nFAILED: {total_errors} error(s) found across {len(results)} log file(s)")
        return 1
    print(f"\nPASSED: No errors found across {len(results)} log file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())