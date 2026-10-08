"""Package frontend resources without requiring Node for editable installs."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        bundle = root / "apps" / "tui" / "dist" / "entry.js"
        includes = build_data.setdefault("force_include", {})
        if self.target_name == "wheel":
            viewer = root / "apps" / "tracing-viewer"
            if viewer.is_dir():
                includes[str(viewer)] = "pico/resources/tracing_viewer"
            if bundle.is_file():
                includes[str(bundle)] = "pico/resources/tui/entry.js"
            else:
                self.app.display_warning("TUI bundle missing. Run npm --prefix apps/tui run build before release.")
        elif self.target_name == "sdist" and bundle.is_file():
            includes[str(bundle)] = "apps/tui/dist/entry.js"
