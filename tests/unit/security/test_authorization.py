"""Tests for pico.security.authorization: the boundaries enforced before an action runs."""

from pathlib import Path

from pico.security.authorization.shell_environment import filter_shell_env


def test_shell_env_uses_allowlist_and_sets_pwd_with_path_fallback(tmp_path: Path) -> None:
    """Command environments carry only allowlisted names, a rewritten PWD and a PATH fallback."""
    env = {"PATH": "/usr/bin", "HOME": "/home/user", "SECRET": "nope"}

    filtered = filter_shell_env(env=env, allowlist=("HOME",), root=tmp_path)

    assert filtered == {"HOME": "/home/user", "PWD": str(tmp_path), "PATH": "/usr/bin"}
