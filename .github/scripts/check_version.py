import re
import sys
import tomllib
from pathlib import Path

CHANGELOG = Path("CHANGELOG.md")
PYPROJECT = Path("pyproject.toml")
TRIPLE = re.compile(r"\d+\.\d+\.\d+")
HEADING = re.compile(r"^#+\s+\[?v?(\d+\.\d+\.\d+)\b")


def project_version(path: Path) -> str:
    """Return the distribution version declared in a pyproject.toml.

    Args:
        path: The pyproject.toml to read.

    Returns:
        The value of ``[project].version``, as written.

    Raises:
        KeyError: The file has no ``[project].version``.
        tomllib.TOMLDecodeError: The file is not valid TOML.
    """
    return str(tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"])


def ordered(head: str, base: str) -> bool:
    """Report whether ``head`` is a greater version than ``base``.

    Args:
        head: The version on the pull request.
        base: The version on ``origin/main``.

    Returns:
        True when both are ``MAJOR.MINOR.PATCH`` and ``head`` compares greater as
        numbers. False otherwise.
    """
    if TRIPLE.fullmatch(head) is None or TRIPLE.fullmatch(base) is None:
        return False
    return _numbers(head) > _numbers(base)


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(field) for field in version.split("."))


def has_entry(version: str) -> bool:
    """Report whether CHANGELOG.md has a heading that names ``version``.

    Args:
        version: The version to look for, such as ``0.4.3``.

    Returns:
        True when a heading's version is exactly ``version``. False when there is no
        such heading, or the file is missing.
    """
    if not CHANGELOG.is_file():
        return False
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        match = HEADING.match(line)
        if match is not None and match.group(1) == version:
            return True
    return False


def main(base_pyproject: Path) -> int:
    """Run the three checks on the checked-out pull request.

    The head version and CHANGELOG.md are read from the working tree, which is the pull
    request head. The base version is read from ``base_pyproject``, which the workflow
    extracts from ``origin/main``. When the version did not move, the other two checks
    are skipped, because they compare against the new version.

    Args:
        base_pyproject: The pyproject.toml as it is on origin/main.

    Returns:
        0 when all three checks pass, 1 when any fails.
    """
    base = project_version(base_pyproject)
    head = project_version(PYPROJECT)

    if head == base:
        sys.stdout.write(
            f"check 1 of 3 failed: the version did not move. pyproject.toml is {head}, "
            "the same as origin/main.\n"
            "  Bump `version` in pyproject.toml and run `uv lock`, which records it in uv.lock.\n"
            "  Patch for a fix or refactor, minor for a capability, major for a break.\n"
        )
        return 1

    failures: list[str] = []
    if not has_entry(head):
        failures.append(
            f"check 2 of 3 failed: CHANGELOG.md has no entry for {head}.\n"
            f"  Add a `## {head}` heading above the newest entry, saying what changed\n"
            "  for someone who was not there.\n"
        )
    if not ordered(head, base):
        failures.append(
            f"check 3 of 3 failed: {head} is not greater than {base}, the version on origin/main.\n"
            "  Versions compare as numbers, so 0.10.0 is greater than 0.9.0. Bump from the base.\n"
        )

    if failures:
        sys.stdout.write("".join(failures))
        return 1
    sys.stdout.write(
        f"all three checks passed: {base} -> {head}, with a CHANGELOG.md entry for {head}.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
