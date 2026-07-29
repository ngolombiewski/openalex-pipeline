"""Measure how much text-context a codebase costs an agent to read.

Off-project meta tool. Reports lines, characters, and an estimated token
count (``chars / chars-per-token``) rolled up by directory grain, plus the
heaviest individual files. By default it enumerates the realistic
agent-context surface via ``git ls-files`` (tracked files only), so virtual
envs, ignored data dirs, and build output are excluded for free.

Usage::

    uv run tools/context_size.py [PATH ...] [options]

Paths are reported relative to the current working directory, so run this
from the directory you want the grain relative to (usually the repo root).
Stdlib only.

Gotchas (learned the hard way):

* ``--depth`` counts path components from the current working directory, not
  relative to the PATH you pass. Pointing at a subtree that is already N
  components deep (e.g. ``src/openalex_pipeline``) collapses everything into
  one row until you raise ``--depth`` past N. Rule of thumb: ``--depth`` =
  (components in the path) + (levels you want to see).
* ``--exclude`` globs must be *quoted* (``--exclude '*.lock'``). Unquoted, your
  shell expands the glob against the cwd before the tool sees it -- which
  silently "works" only when it happens to expand to exactly the file you
  meant. Patterns are matched with ``fnmatch`` against the full cwd-relative
  path, and ``*`` spans ``/``, so ``'docs/*'`` excludes the whole subtree
  (nested files included), not just its immediate children.
"""

from __future__ import annotations

import argparse
import enum
import fnmatch
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

# Detecting a binary file: a NUL byte anywhere in this many leading bytes.
_BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class FileStat:
    """Text measurement of a single file.

    ``chars`` counts Unicode code points (including whitespace and newlines)
    of the UTF-8-decoded content -- that is what an agent actually consumes.
    ``tokens`` is ``round(chars / chars_per_token)`` (banker's rounding; an
    estimate for relative sizing, not an exact budget).
    """

    path: str
    lines: int
    chars: int
    tokens: int


@dataclass(frozen=True)
class GroupStat:
    """Aggregated measurement for one directory group.

    ``key`` is the directory prefix at the chosen depth, ``"."`` for
    root-level files, or ``"<total>"`` for the single depth-0 group.
    """

    key: str
    files: int
    lines: int
    chars: int
    tokens: int


class SkipReason(enum.Enum):
    """Why a listed file was measured as non-text and excluded from totals."""

    SYMLINK = "symlink"
    BINARY = "binary"
    UNREADABLE = "unreadable"


class NotAGitRepo(RuntimeError):
    """Raised by :func:`list_files` when ``use_git`` but cwd is not a work tree."""


def _git(args: Sequence[str]) -> bytes:
    """Run a git command and return raw stdout bytes (``check=True``)."""
    proc = subprocess.run(["git", *args], capture_output=True, check=True)
    return proc.stdout


def _is_git_work_tree() -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == b"true"


def _split_nul(raw: bytes) -> list[str]:
    return [p for p in raw.decode("utf-8", "surrogateescape").split("\0") if p]


def list_files(
    roots: Sequence[str],
    *,
    use_git: bool = True,
    include_untracked: bool = False,
    exclude: Sequence[str] = (),
) -> list[str]:
    """Return the deduplicated, sorted paths to measure.

    ``use_git`` enumerates tracked files via ``git ls-files``;
    ``include_untracked`` additionally adds untracked-but-not-ignored files
    (``--others --exclude-standard``). ``use_git=False`` walks the filesystem
    under each root, skipping any ``.git/`` segment. ``exclude`` drops any path
    matching one of the given globs, matched with ``fnmatch`` against the full
    cwd-relative path (e.g. ``uv.lock``, ``*.lock``, ``docs/*``). Note ``*``
    spans ``/`` (so ``docs/*`` matches nested files too); on the command line
    the pattern must be quoted or the shell expands it first. Symlinks and
    unreadable files are kept in the list here and classified later by
    :func:`measure_file`.

    Paths are returned relative to the current working directory. Raises
    :class:`FileNotFoundError` if a root does not exist, or
    :class:`NotAGitRepo` if ``use_git`` and cwd is not a git work tree.
    """
    for root in roots:
        try:
            Path(root).lstat()
        except FileNotFoundError:
            raise FileNotFoundError(f"root does not exist: {root}") from None

    if use_git:
        if not _is_git_work_tree():
            raise NotAGitRepo(
                "not inside a git work tree; pass --no-git to measure the "
                "filesystem directly"
            )
        found = _split_nul(_git(["ls-files", "-z", "--", *roots]))
        if include_untracked:
            found += _split_nul(
                _git(["ls-files", "-z", "--others", "--exclude-standard", "--", *roots])
            )
    else:
        found = _walk(roots)
    found = [Path(os.path.relpath(p, start=Path.cwd())).as_posix() for p in found]
    if exclude:
        found = [
            p for p in found if not any(fnmatch.fnmatch(p, pat) for pat in exclude)
        ]
    return sorted(dict.fromkeys(found))


def _walk(roots: Sequence[str]) -> list[str]:
    """Filesystem enumeration used when ``use_git=False``; skips ``.git/``."""
    out: list[str] = []
    for root in roots:
        p = Path(root)
        if p.is_file() or p.is_symlink():
            out.append(root)
            continue
        for child in p.rglob("*"):
            if ".git" in child.parts:
                continue
            if child.is_file() or child.is_symlink():
                out.append(str(child))
    return out


def measure_file(path: str, *, chars_per_token: float = 4.0) -> FileStat | SkipReason:
    """Measure ``path`` as UTF-8 text, or return a :class:`SkipReason`.

    Returns ``SkipReason.SYMLINK`` for a symlink (never followed),
    ``SkipReason.BINARY`` when a NUL byte appears in the first
    ``_BINARY_SNIFF_BYTES`` bytes or the content is not valid UTF-8, and
    ``SkipReason.UNREADABLE`` on any IO/OS error. Never raises for a bad file.
    """
    p = Path(path)
    if p.is_symlink():
        return SkipReason.SYMLINK
    try:
        with open(p, "rb") as fh:
            head = fh.read(_BINARY_SNIFF_BYTES)
            if b"\0" in head:
                return SkipReason.BINARY
            raw = head + fh.read()
    except OSError:
        return SkipReason.UNREADABLE
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return SkipReason.BINARY
    chars = len(content)
    return FileStat(
        path=path,
        lines=len(content.splitlines()),
        chars=chars,
        tokens=round(chars / chars_per_token),
    )


def _group_key(path: str, depth: int) -> str:
    if depth <= 0:
        return "<total>"
    p = PurePosixPath(path)
    if len(p.parts) <= depth:
        return str(p.parent)
    return "/".join(p.parts[:depth])


def rollup(stats: Iterable[FileStat], *, depth: int) -> list[GroupStat]:
    """Aggregate file stats into directory groups at ``depth`` path components.

    ``depth`` counts components from the current working directory, not
    relative to any path passed on the command line: a file ``a/b/c.py`` groups
    under ``a/b`` at depth 2 regardless of which root selected it. ``depth <=
    0`` yields a single ``"<total>"`` group. Files with fewer than ``depth``
    components group under their actual parent directory (root-level files
    under ``"."``). Returned sorted by key.
    """
    acc: dict[str, list[int]] = {}
    for s in stats:
        key = _group_key(s.path, depth)
        row = acc.setdefault(key, [0, 0, 0, 0])
        row[0] += 1
        row[1] += s.lines
        row[2] += s.chars
        row[3] += s.tokens
    return [
        GroupStat(key, f, ln, ch, tk) for key, (f, ln, ch, tk) in sorted(acc.items())
    ]


_SORT_FIELDS = {
    "tokens": ("tokens", True),
    "chars": ("chars", True),
    "lines": ("lines", True),
    "files": ("files", True),
    "path": ("key", False),
}


def _sorted_groups(groups: Sequence[GroupStat], sort: str) -> list[GroupStat]:
    field, reverse = _SORT_FIELDS[sort]
    return sorted(groups, key=lambda g: getattr(g, field), reverse=reverse)


def _render_table(
    groups: Sequence[GroupStat],
    total: GroupStat,
    top: Sequence[FileStat],
    skipped: dict[str, int],
) -> str:
    headers = ("Path", "Files", "Lines", "Chars", "Est. Tokens")
    rows = [
        (g.key, f"{g.files:,}", f"{g.lines:,}", f"{g.chars:,}", f"{g.tokens:,}")
        for g in groups
    ]
    total_row = (
        "TOTAL",
        f"{total.files:,}",
        f"{total.lines:,}",
        f"{total.chars:,}",
        f"{total.tokens:,}",
    )
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in (*rows, total_row)))
        for i in range(len(headers))
    ]

    def fmt(cells: Sequence[str]) -> str:
        out = [cells[0].ljust(widths[0])]
        out += [cells[i].rjust(widths[i]) for i in range(1, len(cells))]
        return "  ".join(out)

    lines = [fmt(headers), fmt(["-" * w for w in widths])]
    lines += [fmt(r) for r in rows]
    lines.append(fmt(["-" * w for w in widths]))
    lines.append(fmt(total_row))

    if top:
        lines.append("")
        lines.append("Heaviest files:")
        for f in top:
            lines.append(f"  {f.path}  ({f.chars:,} chars, {f.tokens:,} est. tokens)")

    if skipped:
        summary = ", ".join(f"{n} {reason}" for reason, n in sorted(skipped.items()))
        lines.append("")
        lines.append(f"skipped: {summary}")

    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="context_size",
        description="Report text-context size (chars / est. tokens) by grain.",
    )
    parser.add_argument("paths", nargs="*", default=["."], help="files/dirs to measure")
    parser.add_argument("--depth", type=int, default=2, help="directory rollup grain")
    parser.add_argument("--top", type=int, default=10, help="show N heaviest files")
    parser.add_argument("--cpt", type=float, default=4.0, help="chars per token")
    parser.add_argument("--all", action="store_true", help="include untracked files")
    parser.add_argument("--no-git", action="store_true", help="walk fs instead of git")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="exclude paths matching GLOB (repeatable), e.g. --exclude '*.lock'",
    )
    parser.add_argument(
        "--sort", choices=sorted(_SORT_FIELDS), default="tokens", help="group sort key"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    roots = args.paths or ["."]
    try:
        paths = list_files(
            roots,
            use_git=not args.no_git,
            include_untracked=args.all,
            exclude=args.exclude,
        )
    except (FileNotFoundError, NotAGitRepo) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    stats: list[FileStat] = []
    skipped: dict[str, int] = {}
    for path in paths:
        result = measure_file(path, chars_per_token=args.cpt)
        if isinstance(result, FileStat):
            stats.append(result)
        else:
            skipped[result.value] = skipped.get(result.value, 0) + 1

    groups = _sorted_groups(rollup(stats, depth=args.depth), args.sort)
    total_row = rollup(stats, depth=0)
    total = total_row[0] if total_row else GroupStat("<total>", 0, 0, 0, 0)
    top = (
        sorted(stats, key=lambda s: s.tokens, reverse=True)[: args.top]
        if args.top > 0
        else []
    )

    if args.json:
        print(
            json.dumps(
                {
                    "groups": [asdict(g) for g in groups],
                    "files": [asdict(s) for s in stats],
                    "total": asdict(total),
                    "skipped": skipped,
                    "params": {
                        "depth": args.depth,
                        "chars_per_token": args.cpt,
                        "sort": args.sort,
                        "exclude": args.exclude,
                        "tracked_only": not args.no_git and not args.all,
                    },
                },
                indent=2,
            )
        )
    else:
        print(_render_table(groups, total, top, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
