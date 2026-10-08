"""Regression coverage for import-boundary enforcement."""

from pathlib import Path

import pytest

from scripts.ci.check_architecture import check_architecture


@pytest.mark.parametrize(
    "statement",
    [
        "import pico.interfaces.cli.app",
        "from pico import interfaces",
        "from ..interfaces import cli",
        "def factory():\n    from pico.bootstrap import container",
    ],
)
def test_detects_entry_point_imports(tmp_path: Path, statement: str):
    source = tmp_path / "pico"
    runtime = source / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "example.py").write_text(statement, encoding="utf-8")
    assert check_architecture(source)


def test_annotations_do_not_hide_executable_imports(tmp_path: Path):
    source = tmp_path / "pico"
    runtime = source / "runtime"
    runtime.mkdir(parents=True)
    path = runtime / "example.py"
    path.write_text(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pico.interfaces import cli\n", encoding="utf-8"
    )
    assert not check_architecture(source)
    path.write_text(path.read_text(encoding="utf-8") + "else:\n    from pico.interfaces import cli\n", encoding="utf-8")
    assert check_architecture(source)
