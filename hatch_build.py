"""Package frontend resources without requiring Node for editable installs."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        bundle = root / "apps" / "tui" / "dist" / "entry.js"
        includes = build_data.setdefault("force_include", {})
        if self.target_name == "wheel":
            viewer = root / "apps" / "tracing-viewer" / "dist"
            if (viewer / "server.js").is_file():
                for name in ("server.js", "ui", "descriptors"):
                    includes[str(viewer / name)] = f"pico/resources/tracing_viewer/{name}"
            else:
                self.app.display_warning("Trace viewer bundle missing. Run npm run build:tracing before release.")
            if bundle.is_file():
                includes[str(bundle)] = "pico/resources/tui/entry.js"
            else:
                self.app.display_warning("TUI bundle missing. Run npm --prefix apps/tui run build before release.")
        elif self.target_name == "sdist":
            if bundle.is_file():
                includes[str(bundle)] = "apps/tui/dist/entry.js"
            viewer = root / "apps" / "tracing-viewer" / "dist"
            if (viewer / "server.js").is_file():
                includes[str(viewer)] = "apps/tracing-viewer/dist"
