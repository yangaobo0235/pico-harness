"""Locate installed resources and optional development application sources."""

from pathlib import Path


def package_path(*parts: str) -> Path:
    """Return a resource path inside the installed Python package."""
    return Path(__file__).resolve().parent.joinpath(*parts)


def source_app(name: str) -> Path | None:
    """Find an application only when this package belongs to a src checkout."""
    package_root = Path(__file__).resolve().parent.parent
    for candidate in package_root.parents:
        if candidate / "src" / "pico" == package_root and (candidate / "pyproject.toml").is_file():
            app = candidate / "apps" / name
            return app if app.is_dir() else None
    return None
