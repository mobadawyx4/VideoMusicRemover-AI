#!/usr/bin/env python3
"""Verify that installed Python distributions satisfy a requirements file.

Used by the installers to avoid reinstalling unchanged dependencies. The check
uses only the standard library so it can run inside a freshly created virtual
environment before any third-party packages are installed.

Exit codes:
    0  All requirements are installed and satisfy their constraints.
    1  One or more requirements are missing or do not satisfy their constraints.
    2  The requirements file could not be parsed or read.
"""

from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

REQUIREMENT_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"\s*(?:\[(?P<extras>[^\]]*)\])?"
    r"\s*(?:(?P<operator>==|>=|<=|~=|!=|>|<)\s*(?P<version>[^;\s,]+))?"
)


class Requirement(NamedTuple):
    name: str
    operator: Optional[str]
    version: Optional[str]
    raw: str


def parse_requirements(
    lines: Iterable[str], base_dir: Optional[Path] = None
) -> list[Requirement]:
    """Parse the subset of requirements syntax used by this project.

    ``-r``/``--requirement`` include directives are expanded when ``base_dir``
    is provided so files such as ``requirements-dev.txt`` can be checked too.
    """
    parsed: list[Requirement] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            if base_dir is None:
                raise ValueError(
                    f"Cannot resolve include without a base directory: {line}"
                )
            target = line.split(None, 1)[1].strip()
            included = (base_dir / target).resolve()
            try:
                included_lines = included.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise ValueError(f"Could not read included file {included}: {exc}")
            parsed.extend(parse_requirements(included_lines, included.parent))
            continue
        if line.startswith("-"):
            raise ValueError(f"Unsupported requirement directive: {line}")
        # Strip inline comments and environment markers; this project does not
        # require markers for runtime dependencies.
        line = re.split(r"\s+#", line, 1)[0].strip()
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        match = REQUIREMENT_RE.match(line)
        if not match:
            raise ValueError(f"Could not parse requirement: {raw_line.strip()}")
        parsed.append(
            Requirement(
                name=match.group("name"),
                operator=match.group("operator"),
                version=match.group("version"),
                raw=line,
            )
        )
    return parsed


def release_tuple(version: str) -> tuple[int, ...]:
    """Return a comparable numeric release tuple for common PEP 440 versions.

    Local version labels are ignored and trailing zero segments are trimmed so
    that ``2.0``, ``2.0.0`` and ``2.0.0+local`` compare as equal (PEP 440).
    """
    core = version.strip().split("+", 1)[0]
    parts: list[int] = []
    for segment in re.split(r"[._-]", core):
        number = re.match(r"\d+", segment)
        if not number:
            break
        parts.append(int(number.group(0)))
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts) or (0,)


def satisfies(installed: str, operator: Optional[str], required: Optional[str]) -> bool:
    """Check an installed version against a simple requirements specifier."""
    if not operator or not required:
        return True

    installed_release = release_tuple(installed)
    required_release = release_tuple(required)

    if operator == "==":
        if required.endswith(".*"):
            prefix = release_tuple(required[:-2])
            return installed_release[: len(prefix)] == prefix
        return installed_release == required_release
    if operator == "!=":
        return installed_release != required_release
    if operator == ">=":
        return installed_release >= required_release
    if operator == ">":
        return installed_release > required_release
    if operator == "<=":
        return installed_release <= required_release
    if operator == "<":
        return installed_release < required_release
    if operator == "~=":
        if installed_release < required_release:
            return False
        # ~= X.Y is compatible with the X.* series; ~= X.Y.Z with X.Y.*.
        if len(required_release) == 1:
            return installed_release[0] == required_release[0]
        prefix = required_release[:-1]
        return installed_release[: len(prefix)] == prefix
    raise ValueError(f"Unsupported operator: {operator}")


def check(requirements: Iterable[Requirement]) -> tuple[int, list[str]]:
    """Return an exit code and human-readable problem descriptions."""
    problems: list[str] = []
    checked = 0
    for requirement in requirements:
        checked += 1
        try:
            installed_version = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            problems.append(f"MISSING  {requirement.raw}")
            continue
        except Exception as exc:  # pragma: no cover - metadata backend failure
            problems.append(f"ERROR    {requirement.raw}: {exc}")
            continue

        if not satisfies(installed_version, requirement.operator, requirement.version):
            problems.append(
                f"OUTDATED {requirement.raw} (installed: {installed_version})"
            )

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1, problems

    print(f"OK: {checked} requirement(s) satisfied")
    return 0, problems


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check installed distributions against a requirements file."
    )
    parser.add_argument("requirements", type=Path, help="Path to requirements.txt")
    args = parser.parse_args(argv)

    try:
        lines = args.requirements.read_text(encoding="utf-8").splitlines()
        requirements = parse_requirements(lines, args.requirements.parent)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    exit_code, _ = check(requirements)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
