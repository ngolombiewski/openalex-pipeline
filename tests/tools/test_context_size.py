"""Tests for tools/context_size.py, written against its pinned contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# tools/ is an off-project meta dir, not an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools import context_size as cs  # noqa: E402


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)


# --- measure_file -----------------------------------------------------------


def test_known_counts(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("abcdefghijkl\n")  # 12 chars + newline = 13
    stat = cs.measure_file(str(f), chars_per_token=4.0)
    assert isinstance(stat, cs.FileStat)
    assert (stat.chars, stat.lines, stat.tokens) == (13, 1, round(13 / 4))


def test_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    stat = cs.measure_file(str(f))
    assert isinstance(stat, cs.FileStat)
    assert (stat.chars, stat.lines, stat.tokens) == (0, 0, 0)


def test_multiline_no_trailing_newline(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a\nb")
    stat = cs.measure_file(str(f))
    assert isinstance(stat, cs.FileStat)
    assert (stat.chars, stat.lines) == (3, 2)


def test_unicode_is_codepoints_not_bytes(tmp_path):
    f = tmp_path / "u.txt"
    f.write_text("café\n")  # 5 code points, 6 UTF-8 bytes
    stat = cs.measure_file(str(f))
    assert isinstance(stat, cs.FileStat)
    assert stat.chars == 5


def test_custom_cpt(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("abcdefghijkl")  # 12 chars
    stat = cs.measure_file(str(f), chars_per_token=3.0)
    assert isinstance(stat, cs.FileStat)
    assert stat.tokens == 4


def test_binary_nul(tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"ab\x00cd")
    assert cs.measure_file(str(f)) is cs.SkipReason.BINARY


def test_invalid_utf8(tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"\xff\xfe\xfa")  # no NUL, but not valid UTF-8
    assert cs.measure_file(str(f)) is cs.SkipReason.BINARY


def test_symlink_not_followed(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("hello\n")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    assert cs.measure_file(str(link)) is cs.SkipReason.SYMLINK


# --- list_files -------------------------------------------------------------


def test_git_tracked_only(tmp_path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "tracked.txt").write_text("x")
    (tmp_path / "ignored.txt").write_text("x")
    (tmp_path / "untracked.txt").write_text("x")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    subprocess.run(
        ["git", "add", "tracked.txt", ".gitignore"], cwd=tmp_path, check=True
    )
    monkeypatch.chdir(tmp_path)
    found = cs.list_files(["."])
    assert "tracked.txt" in found
    assert "ignored.txt" not in found
    assert "untracked.txt" not in found


def test_include_untracked(tmp_path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "tracked.txt").write_text("x")
    (tmp_path / "untracked.txt").write_text("x")
    (tmp_path / "ignored.txt").write_text("x")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    subprocess.run(
        ["git", "add", "tracked.txt", ".gitignore"], cwd=tmp_path, check=True
    )
    monkeypatch.chdir(tmp_path)
    found = cs.list_files(["."], include_untracked=True)
    assert "untracked.txt" in found
    assert "ignored.txt" not in found


def test_no_git_walk_skips_dotgit(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    monkeypatch.chdir(tmp_path)
    found = cs.list_files(["."], use_git=False)
    assert any(p.endswith("a.txt") for p in found)
    assert not any(".git" in Path(p).parts for p in found)


def test_no_git_absolute_root_returns_cwd_relative_paths(tmp_path, monkeypatch):
    root = tmp_path / "nested"
    root.mkdir()
    (root / "a.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    found = cs.list_files([str(root)], use_git=False)
    assert found == ["nested/a.txt"]


def test_git_paths_are_relative_to_cwd(tmp_path, monkeypatch):
    _git_init(tmp_path)
    root = tmp_path / "nested"
    root.mkdir()
    (root / "a.txt").write_text("x")
    subprocess.run(["git", "add", "nested/a.txt"], cwd=tmp_path, check=True)
    monkeypatch.chdir(root)
    assert cs.list_files(["."]) == ["a.txt"]


def test_not_a_git_repo_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(cs.NotAGitRepo):
        cs.list_files(["."], use_git=True)


@pytest.mark.parametrize("use_git", [True, False])
def test_missing_root_raises(tmp_path, monkeypatch, use_git):
    _git_init(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="root does not exist: missing"):
        cs.list_files(["missing"], use_git=use_git)


def test_exclude_glob(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.lock").write_text("x")
    (tmp_path / "c.lock").write_text("x")
    monkeypatch.chdir(tmp_path)
    found = cs.list_files(["."], use_git=False, exclude=["*.lock"])
    assert any(p.endswith("a.txt") for p in found)
    assert not any(p.endswith(".lock") for p in found)


def test_exclude_exact_path(tmp_path, monkeypatch):
    (tmp_path / "uv.lock").write_text("x")
    (tmp_path / "keep.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    found = cs.list_files(["."], use_git=False, exclude=["uv.lock"])
    assert "uv.lock" not in found
    assert any(p.endswith("keep.txt") for p in found)


def test_dedup_overlapping_roots(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    found = cs.list_files(["a", "a/b.txt"], use_git=False)
    assert sum("b.txt" in p for p in found) == 1


# --- rollup -----------------------------------------------------------------


def _fs(path, chars=10):
    return cs.FileStat(path=path, lines=1, chars=chars, tokens=chars)


def test_depth_1_groups_by_top_dir():
    stats = [_fs("dbt/models/x.sql"), _fs("dbt/tests/y.sql"), _fs("README.md")]
    groups = {g.key: g for g in cs.rollup(stats, depth=1)}
    assert groups["dbt"].files == 2
    assert groups["."].files == 1


def test_depth_2_splits_nested():
    stats = [_fs("dbt/models/x.sql"), _fs("dbt/tests/y.sql"), _fs("README.md")]
    keys = {g.key for g in cs.rollup(stats, depth=2)}
    assert keys == {"dbt/models", "dbt/tests", "."}


def test_depth_0_single_total():
    stats = [_fs("dbt/models/x.sql", 10), _fs("README.md", 5)]
    groups = cs.rollup(stats, depth=0)
    assert len(groups) == 1
    assert groups[0].key == "<total>"
    assert groups[0].chars == 15


def test_shallow_file_under_depth():
    groups = {g.key: g for g in cs.rollup([_fs("README.md")], depth=2)}
    assert "." in groups


# --- CLI integration --------------------------------------------------------


def _make_repo(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "big.py").write_text("x" * 100 + "\n")
    (tmp_path / "small.md").write_text("y" * 10 + "\n")
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)


def test_main_json_on_temp_repo(tmp_path, monkeypatch, capsys):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = cs.main(["--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    file_chars = sum(f["chars"] for f in payload["files"])
    assert payload["total"]["chars"] == file_chars == 112  # 101 + 11
    assert payload["skipped"] == {"binary": 1}


def test_main_sorts_by_tokens_desc(tmp_path, monkeypatch, capsys):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = cs.main(["--json", "--depth", "1", "--sort", "tokens"])
    assert rc == 0
    groups = json.loads(capsys.readouterr().out)["groups"]
    tokens = [g["tokens"] for g in groups]
    assert tokens == sorted(tokens, reverse=True)


def test_main_not_a_repo_returns_1(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = cs.main([])
    assert rc == 1
    assert "not inside a git work tree" in capsys.readouterr().err


def test_main_missing_root_returns_1(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = cs.main(["missing", "--no-git"])
    assert rc == 1
    assert "root does not exist: missing" in capsys.readouterr().err
