"""Tests for the memory-system hooks' path relativization.

WHY THIS EXISTS
---------------
``.claude/PROGRESS.md`` is version-controlled and the lifecycle hooks append to
it on nearly every tool call. If those entries carry absolute paths, two things
break at once: the committed log leaks ``/home/<user>/...`` into a public repo,
and every developer's clone re-churns the same lines. ``_lib.relativize_paths``
is the single choke point that prevents it -- every hook routes through
``append_progress``, which calls it.

These tests are torch-free: they load ``.claude/hooks/_lib.py`` directly with
``CLAUDE_PROJECT_DIR``/``HOME`` pinned, because both are resolved at import time.

Run: ``python -m pytest tests/test_hook_path_relativization.py -v``
"""

from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
HOOK_LIB = REPO / ".claude" / "hooks" / "_lib.py"

FAKE_HOME = "/home/someuser"
FAKE_PROJECT = f"{FAKE_HOME}/Workspace/myrepo"


def _load_lib(monkeypatch, project=FAKE_PROJECT, home=FAKE_HOME):
    """Import _lib.py fresh with PROJECT_DIR and HOME pinned to fakes."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", project)
    monkeypatch.setenv("HOME", home)
    spec = importlib.util.spec_from_file_location("_hooklib_under_test", HOOK_LIB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# relativize_paths
# --------------------------------------------------------------------------

def test_project_file_becomes_repo_relative(monkeypatch):
    lib = _load_lib(monkeypatch)
    got = lib.relativize_paths(f"edited `{FAKE_PROJECT}/docs/v0.3-eval-report.md`")
    assert got == "edited `docs/v0.3-eval-report.md`"


def test_bare_project_dir_becomes_dot(monkeypatch):
    lib = _load_lib(monkeypatch)
    assert lib.relativize_paths(f"cd {FAKE_PROJECT}") == "cd ."


def test_path_outside_project_but_under_home_collapses_to_tilde(monkeypatch):
    lib = _load_lib(monkeypatch)
    got = lib.relativize_paths(f"created `{FAKE_HOME}/.claude/projects/x/memory/MEMORY.md`")
    assert got == "created `~/.claude/projects/x/memory/MEMORY.md`"


def test_project_is_substituted_before_home(monkeypatch):
    # The project lives under HOME; substituting HOME first would leave
    # "~/Workspace/myrepo/f.py" instead of the repo-relative "f.py".
    lib = _load_lib(monkeypatch)
    assert lib.relativize_paths(f"{FAKE_PROJECT}/f.py") == "f.py"


def test_multiple_paths_in_one_line(monkeypatch):
    lib = _load_lib(monkeypatch)
    got = lib.relativize_paths(f"cp {FAKE_PROJECT}/a.txt {FAKE_HOME}/backup/a.txt")
    assert got == "cp a.txt ~/backup/a.txt"


def test_paths_of_other_users_are_left_alone(monkeypatch):
    # Only THIS machine's home/project are rewritten; a path quoted from
    # elsewhere (e.g. a remote box) is content, not a local leak.
    lib = _load_lib(monkeypatch)
    text = "/home/otheruser/data/encoded"
    assert lib.relativize_paths(text) == text


def test_text_without_paths_is_unchanged(monkeypatch):
    lib = _load_lib(monkeypatch)
    text = "git commit -m 'fix: no paths here'"
    assert lib.relativize_paths(text) == text


# --------------------------------------------------------------------------
# append_progress: the integration that actually writes PROGRESS.md
# --------------------------------------------------------------------------

def test_append_progress_writes_no_absolute_paths(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = home / "Workspace" / "repo"
    (project / ".claude").mkdir(parents=True)
    progress = project / ".claude" / "PROGRESS.md"
    progress.write_text("# PROGRESS\n\n---\n\n", encoding="utf-8")

    lib = _load_lib(monkeypatch, project=str(project), home=str(home))
    lib.append_progress(
        status="done",
        kind="edit",
        summary=f"edited `{project}/docs/x.md`",
        detail=f"also touched {home}/.config/y.json",
    )

    written = progress.read_text(encoding="utf-8")
    assert str(project) not in written
    assert str(home) not in written
    assert "edited `docs/x.md`" in written
    assert "~/.config/y.json" in written


def test_append_progress_still_redacts_secrets(monkeypatch, tmp_path):
    # Relativization must not displace the existing secret scrub.
    project = tmp_path / "repo"
    (project / ".claude").mkdir(parents=True)
    progress = project / ".claude" / "PROGRESS.md"
    progress.write_text("# PROGRESS\n\n---\n\n", encoding="utf-8")

    lib = _load_lib(monkeypatch, project=str(project), home=str(tmp_path))
    lib.append_progress(
        status="done", kind="exec",
        summary="export HF_TOKEN=hf_" + "a" * 30,
    )

    written = progress.read_text(encoding="utf-8")
    assert "[REDACTED]" in written
    assert "hf_" + "a" * 30 not in written


if __name__ == "__main__":
    import sys
    raise SystemExit(__import__("pytest").main([__file__, "-v"] + sys.argv[1:]))
