"""Tests for scripts.ci.check_architecture: executable import boundaries of `src/pico`."""

import ast
from pathlib import Path

import pytest

from scripts.ci.check_architecture import check_architecture, runtime_imports


def _write_module(tmp_path: Path, relative_path: str, statement: str) -> Path:
    """Create one module under a throwaway `pico` source root and return its path."""
    path = tmp_path / "pico" / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(statement, encoding="utf-8")
    return path


def test_real_source_tree_is_clean() -> None:
    """The shipped package violates none of its own boundary rules."""
    assert check_architecture() == []


@pytest.mark.parametrize(
    "statement",
    [
        "import pico.interfaces.cli.app",
        "from pico import interfaces",
        "from ..interfaces import cli",
        "def factory():\n    from pico.bootstrap import container",
    ],
)
def test_detects_entry_point_imports(tmp_path: Path, statement: str) -> None:
    """Execution layers may not reach into the CLI or the composition root, even from a function body."""
    _write_module(tmp_path, "runtime/example.py", statement)

    assert check_architecture(tmp_path / "pico")


@pytest.mark.parametrize("retired", ["pico.evaluator", "pico.metrics", "pico.models", "pico.memory"])
def test_detects_retired_module_paths(tmp_path: Path, retired: str) -> None:
    """Names retired by the layering stay banned instead of lingering as aliases."""
    _write_module(tmp_path, "runtime/example.py", f"from {retired} import thing\n")

    findings = check_architecture(tmp_path / "pico")

    assert any("retired module path" in finding for finding in findings)


@pytest.mark.parametrize("repository_package", ["tests", "scripts", "benchmarks"])
def test_detects_product_code_importing_repository_only_code(tmp_path: Path, repository_package: str) -> None:
    """Product modules must not depend on anything that only exists inside this repository."""
    _write_module(tmp_path, "capabilities/example.py", f"import {repository_package}.helper\n")

    findings = check_architecture(tmp_path / "pico")

    assert any("product code imports repository-only code" in finding for finding in findings)


def test_foundation_module_may_not_import_a_feature(tmp_path: Path) -> None:
    """`contracts` and `shared` hold cross-layer vocabulary and must not pull in a feature layer."""
    _write_module(tmp_path, "contracts/example.py", "from pico.runtime.agent import agent\n")

    findings = check_architecture(tmp_path / "pico")

    assert any("foundation module imports a feature" in finding for finding in findings)


def test_foundation_module_may_import_shared(tmp_path: Path) -> None:
    """`contracts` may lean on `shared` or on itself without crossing a boundary."""
    _write_module(tmp_path, "contracts/example.py", "from pico.shared import text\n")
    _write_module(tmp_path, "contracts/other.py", "from pico.contracts import turns\n")
    _write_module(tmp_path, "shared/other.py", "from pico.shared import paths\n")

    assert check_architecture(tmp_path / "pico") == []


def test_shared_is_treated_as_a_feature_by_the_foundation_rule(tmp_path: Path) -> None:
    """The foundation allowance is ``{own group, shared}``, so `shared` cannot import `contracts`."""
    _write_module(tmp_path, "shared/other.py", "from pico.contracts import turns\n")

    findings = check_architecture(tmp_path / "pico")

    assert findings == [
        "shared/other.py:1: foundation module imports a feature: pico.contracts",
        "shared/other.py:1: foundation module imports a feature: pico.contracts.turns",
    ]


def test_annotations_do_not_hide_executable_imports(tmp_path: Path) -> None:
    """TYPE_CHECKING-only branches are skipped, but a runtime `else` branch is still flagged."""
    path = _write_module(
        tmp_path,
        "runtime/example.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pico.interfaces import cli\n",
    )
    assert not check_architecture(tmp_path / "pico")

    path.write_text(path.read_text(encoding="utf-8") + "else:\n    from pico.interfaces import cli\n", encoding="utf-8")
    assert check_architecture(tmp_path / "pico")


def test_relative_import_is_resolved_to_its_absolute_module(tmp_path: Path) -> None:
    """Relative imports are expanded against their package so boundaries are checked on real names."""
    path = _write_module(tmp_path, "runtime/sub/example.py", "from ...interfaces import cli\n")

    tree = ast.parse(path.read_text(encoding="utf-8"))
    resolved = {module for _, module in runtime_imports(tree, "pico.runtime.sub")}

    assert "pico.interfaces" in resolved
    assert any("pico.interfaces" in finding for finding in check_architecture(tmp_path / "pico"))


def test_runtime_imports_keeps_star_export_module_only(tmp_path: Path) -> None:
    """A star import yields the module itself rather than a fabricated symbol name."""
    path = _write_module(tmp_path, "runtime/example.py", "from pico.shared import *\n")

    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = [module for _, module in runtime_imports(tree, "pico.runtime")]

    assert "pico.shared" in modules
    assert not any(module.startswith("pico.shared.") for module in modules)
