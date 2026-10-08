"""Check the executable import boundaries of the Pico source package."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "pico"
RETIRED = ("pico.agent", "pico.cli", "pico.spine", "pico.memory_engine", "pico.context_engine", "pico.tui_rpc")
PROTECTED = {"runtime", "capabilities", "integrations", "observability", "security", "config", "extensions"}


def runtime_imports(tree: ast.AST, package: str):
    """Exclude annotations-only branches while retaining imports inside functions."""
    if isinstance(tree, ast.If) and ast.unparse(tree.test) in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}:
        for child in tree.orelse:
            yield from runtime_imports(child, package)
        return
    if isinstance(tree, ast.Import):
        for alias in tree.names:
            yield tree.lineno, alias.name
    elif isinstance(tree, ast.ImportFrom):
        module = tree.module or ""
        if tree.level:
            parts = package.split(".")
            base = parts[: len(parts) - tree.level + 1]
            module = ".".join([*base, *([module] if module else [])])
        yield tree.lineno, module
        for alias in tree.names:
            if alias.name != "*":
                yield tree.lineno, f"{module}.{alias.name}" if module else alias.name
    for node in ast.iter_child_nodes(tree):
        yield from runtime_imports(node, package)


def check_architecture(source: Path = SOURCE) -> list[str]:
    findings: list[str] = []
    for path in sorted(source.rglob("*.py")):
        relative = path.relative_to(source)
        group = relative.parts[0] if len(relative.parts) > 1 else "package"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = ".".join(["pico", *relative.parts[:-1]])
        for line, module in runtime_imports(tree, package):
            reason = None
            if module.split(".", 1)[0] in {"tests", "scripts", "benchmarks"}:
                reason = "product code imports repository-only code"
            elif any(module == old or module.startswith(old + ".") for old in RETIRED):
                reason = "retired module path"
            elif group in PROTECTED and module.startswith(("pico.interfaces", "pico.bootstrap")):
                reason = "execution module imports an entry point or composition root"
            elif group in {"contracts", "shared"} and module.startswith("pico."):
                target = module.split(".")[1]
                if target not in {group, "shared"}:
                    reason = "foundation module imports a feature"
            if reason:
                findings.append(f"{relative.as_posix()}:{line}: {reason}: {module}")
    return findings


def main() -> int:
    findings = check_architecture()
    for finding in findings:
        print(finding)
    if not findings:
        print("architecture: OK")
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())
