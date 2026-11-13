#!/usr/bin/env python3
"""Run test suite with optimal parallelization.

Strategy:
- Non-tkinter tests: parallel (-n auto)
- Tkinter tests: sequential
- Frozen/Integration/Geometry: sequential
"""

import subprocess
import sys
import time

NON_TKINTER = [
    "tests/test_archive_service.py",
    "tests/test_catalog_extract_lifecycle.py",
    "tests/test_catalog_library.py",
    "tests/test_catalog_page.py",
    "tests/test_catalog_render.py",
    "tests/test_catalog_status.py",
    "tests/test_category_evidence.py",
    "tests/test_contrast.py",
    "tests/test_conversion_safety.py",
    "tests/test_dead_code.py",
    "tests/test_diagnostics.py",
    "tests/test_events_state.py",
    "tests/test_extract_service.py",
    "tests/test_filename_utils.py",
    "tests/test_installer_detect.py",
    "tests/test_library_summary.py",
    "tests/test_platform.py",
    "tests/test_release_structure.py",
    "tests/test_services.py",
    "tests/test_tools.py",
    "tests/test_uri_actions.py",
    "tests/test_zero_skips.py",
]

TKINTER = [
    "tests/test_artwork_render.py",
    "tests/test_batch_extract.py",
    "tests/test_displayed_data.py",
    "tests/test_lifecycle.py",
    "tests/test_project_state_guard.py",
    "tests/test_regressions.py",
    "tests/test_render_integrity.py",
    "tests/test_review_context_panels.py",
    "tests/test_run_reporting.py",
    "tests/test_setup_flow.py",
    "tests/test_ui_geometry.py",
    "tests/test_workflow_smoke.py",
]

FROZEN_INTEGRATION = [
    "tests/test_frozen_build.py",
    "tests/test_end_to_end.py",
    "tests/test_workflow_smoke.py",
]


def run_tests(test_files, parallel=False, description=""):
    cmd = ["runtime/python.exe", "-m", "pytest", "-c", "tests/pytest.ini"] + test_files
    if parallel:
        cmd += ["-n", "auto", "--dist=loadfile"]
    cmd += ["--tb=short"]

    print(f"\n{'=' * 60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'=' * 60}")

    start = time.time()
    result = subprocess.run(cmd, cwd=r"E:\Game Installers\0. Steam Game Organizer")
    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s (exit code: {result.returncode})")
    return result.returncode, elapsed


def main():
    total_start = time.time()

    # 1. Non-tkinter tests in parallel
    rc1, t1 = run_tests(NON_TKINTER, parallel=True, description="Non-tkinter tests (parallel)")

    # 2. Tkinter tests sequential
    rc2, t2 = run_tests(TKINTER, parallel=False, description="Tkinter tests (sequential)")

    # 3. Frozen/Integration tests sequential
    rc3, t3 = run_tests(FROZEN_INTEGRATION, parallel=False, description="Frozen/Integration tests (sequential)")

    total = time.time() - total_start

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Non-tkinter (parallel):   {t1:.1f}s  {'PASS' if rc1 == 0 else 'FAIL'}")
    print(f"  Tkinter (sequential):     {t2:.1f}s  {'PASS' if rc2 == 0 else 'FAIL'}")
    print(f"  Frozen/Integration:       {t3:.1f}s  {'PASS' if rc3 == 0 else 'FAIL'}")
    print(f"  TOTAL:                    {total:.1f}s")
    print(f"  Overall:                  {'PASS' if all(r == 0 for r in [rc1, rc2, rc3]) else 'FAIL'}")

    return 0 if all(r == 0 for r in [rc1, rc2, rc3]) else 1


if __name__ == "__main__":
    sys.exit(main())
