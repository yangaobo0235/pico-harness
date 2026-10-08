"""Contract checks for the public Pico installers."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["scripts/install/install.sh", "scripts/install/install.ps1"])
def test_installer_builds_from_github_source_without_release_service(name: str) -> None:
    source = (ROOT / name).read_text(encoding="utf-8")

    assert "github.com/yangaobo0235/pico-harness" in source
    assert "PICO_REPO_URL" in source
    assert "PICO_WHEEL_URL" in source
    # 安装器不得依赖任何 Release 服务或私有制品鉴权。
    assert "releases/latest" not in source
    assert "api.github.com" not in source
    assert "GITHUB_TOKEN" not in source
    assert "gitee" not in source.lower()
    assert "myna" not in source.lower()
    assert "--with-executables-from" not in source
    assert "pico onboard --skip-memory" in source
    assert "PICO_NPM_REGISTRY" in source
    assert "PICO_NODE_CHECKSUM_BASE" in source
    assert "PICO_PYPI_INDEX" in source


@pytest.mark.parametrize("name", ["scripts/install/install.sh", "scripts/install/install.ps1"])
def test_installer_builds_tui_bundle_before_uv_install(name: str) -> None:
    source = (ROOT / name).read_text(encoding="utf-8")

    # TUI bundle 是被 Git 忽略的构建产物，安装路径必须先保证它存在。
    assert "build_tui_if_needed" in source or "Build-TuiBundle" in source
    assert "apps/tui" in source
    assert "npm" in source
    build_pos = min(source.index(m) for m in ("build_tui_if_needed", "Build-TuiBundle") if m in source)
    install_pos = source.index("tool install")
    assert build_pos < install_pos


def test_posix_installer_clones_into_pico_home_src() -> None:
    source = (ROOT / "scripts/install/install.sh").read_text(encoding="utf-8")

    assert 'git clone --depth 1 "$PICO_REPO_URL" "$src_dir"' in source
    assert 'src_dir="$PICO_HOME/src/pico-harness"' in source
    assert 'uv tool install --force "$src_dir[channels]"' in source


def test_powershell_installer_clones_into_pico_home_src() -> None:
    source = (ROOT / "scripts/install/install.ps1").read_text(encoding="utf-8")

    assert "git clone --depth 1 $PicoRepoUrl $srcDir" in source
    assert 'Join-Path $PicoHome "src\\pico-harness"' in source
    assert "Install-FromCheckout $UvPath $srcDir" in source


@pytest.mark.parametrize("name", ["scripts/install/install.sh", "scripts/install/install.ps1"])
def test_installer_fails_closed_when_node_checksum_is_unavailable(name: str) -> None:
    source = (ROOT / name).read_text(encoding="utf-8")

    assert "skipping checksum verification" not in source.lower()
    assert "could not fetch node shasums256.txt" in source.lower()
    assert "https://nodejs.org/dist" in source
