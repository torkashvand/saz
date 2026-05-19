"""Assert per-package branch coverage thresholds from the testing report.

Usage:
    coverage run -m pytest -n 0
    python scripts/check_coverage.py

Exits non-zero if any package falls below its declared threshold. Run
after a successful coverage-instrumented test session; reads the .coverage
data file via the coverage.py API rather than parsing report text.
"""

from __future__ import annotations

import sys

from coverage import Coverage

# Per-package threshold table from the testing report.
# Keys are filesystem prefixes within `saz/`; values are the minimum
# branch-coverage percentage (0–100) required for any file under that prefix
# to be considered passing.
THRESHOLDS: list[tuple[str, float]] = [
    ("saz/compiler/", 95.0),
    ("saz/agents/", 90.0),
    ("saz/engine/", 90.0),
    ("saz/policies/", 90.0),
    ("saz/api/routes/", 85.0),
    ("saz/repositories/", 80.0),
    ("saz/tools/", 80.0),
]


def _percent(missing: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return 100.0 * (1.0 - missing / total)


def main() -> int:
    cov = Coverage()
    try:
        cov.load()
    except Exception as exc:
        print(f"could not load coverage data: {exc}", file=sys.stderr)
        return 2

    data = cov.get_data()
    measured_files = sorted(data.measured_files())
    if not measured_files:
        print("no coverage data found — run `coverage run -m pytest` first", file=sys.stderr)
        return 2

    failures: list[str] = []

    for prefix, threshold in THRESHOLDS:
        package_files = [
            f for f in measured_files if f"/{prefix}" in f or f.endswith(prefix.rstrip("/"))
        ]
        # Coverage stores absolute paths; loosen the match for portability.
        package_files = [f for f in measured_files if prefix in f]
        if not package_files:
            print(f"warn: no measured files for {prefix}", file=sys.stderr)
            continue

        for path in package_files:
            analysis = cov.analysis2(path)
            # analysis2 returns: (filename, executable_lines, excluded, missing, missing_formatted)
            executable = len(analysis[1])
            missing = len(analysis[3])
            pct = _percent(missing, executable)
            if pct < threshold:
                failures.append(f"  {path}: {pct:.1f}% < {threshold:.1f}% required")

    if failures:
        print("Coverage thresholds not met:")
        for line in failures:
            print(line)
        return 1

    print("All per-package coverage thresholds met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
