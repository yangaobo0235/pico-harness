#!/bin/sh
# Pico 国内一键安装脚本（macOS/Linux）。
#
#   远程：curl -fsSL https://raw.githubusercontent.com/yangaobo0235/pico-harness/main/install.sh | sh
#   本地：git clone ... && cd pico-harness && ./install.sh
#
# 目标：让全新机器无需手工步骤即可从任意目录运行 `pico`。脚本具备幂等性，
# 会探测已有内容并只补齐缺项：
#   1. uv            （Python 工具链与包管理器）
#   2. Node.js >= 22 （TUI 运行时；系统缺少时私有安装）
#   3. pico          （作为全局 uv 工具安装到 ~/.local/bin/pico）
#
# 远程模式从 GitHub 克隆源码并本地构建 TUI bundle；可用 PICO_REPO_URL 换源，
# 或用 PICO_WHEEL_URL 直接安装经过信任的 wheel。
#
# 刻意使用 POSIX sh，使脚本不仅能在 Bash 下运行，也支持 dash/ash。
set -eu

# --- 配置 -----------------------------------------------------------------
MIN_NODE_MAJOR=22
PICO_HOME="${PICO_HOME:-${HOME:?HOME is required, or set PICO_HOME explicitly}/.pico}"
NODE_RUNTIME_DIR="$PICO_HOME/runtime"
PICO_REPO_URL="${PICO_REPO_URL:-https://github.com/yangaobo0235/pico-harness.git}"
PICO_NODE_MIRROR="${PICO_NODE_MIRROR:-https://mirrors.aliyun.com/nodejs-release}"
PICO_NODE_CHECKSUM_BASE="${PICO_NODE_CHECKSUM_BASE:-https://nodejs.org/dist}"
PICO_NPM_REGISTRY="${PICO_NPM_REGISTRY:-https://registry.npmmirror.com}"
PICO_PYPI_INDEX="${PICO_PYPI_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PICO_UV_INSTALL_URL="${PICO_UV_INSTALL_URL:-https://astral.sh/uv/install.sh}"

# --- 格式化输出 ------------------------------------------------------------
info()  { printf '\033[1;34m>\033[0m %s\n' "$1"; }
ok()    { printf '\033[1;32m+\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m!\033[0m %s\n' "$1" >&2; }
die()   { printf '\033[1;31mx\033[0m %s\n' "$1" >&2; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }

# --- 0. 平台探测 -----------------------------------------------------------
detect_platform() {
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os" in
    Darwin) NODE_OS="darwin" ;;
    Linux)  NODE_OS="linux" ;;
    *) die "Unsupported OS: $os (only macOS / Linux; on Windows use install.ps1)" ;;
  esac
  case "$arch" in
    arm64|aarch64) NODE_ARCH="arm64" ;;
    x86_64|amd64)  NODE_ARCH="x64" ;;
    *) die "Unsupported architecture: $arch" ;;
  esac
}

# --- 1. 确保 uv 可用 -------------------------------------------------------
ensure_uv() {
  if have uv; then
    ok "uv already installed ($(uv --version))"
    return
  fi
  info "uv not found, installing..."
  curl -fsSL "$PICO_UV_INSTALL_URL" | sh
  # uv 安装到 ~/.local/bin（或 $XDG_BIN_HOME）；即使 shell 配置尚未重新加载，
  # 也要让脚本后续步骤能找到它。
  export PATH="$HOME/.local/bin:$PATH"
  have uv || die "uv still unavailable after install; check PATH (expected in ~/.local/bin)"
  ok "uv installed"
}

# --- 2. 确保 Node >= 22 ----------------------------------------------------
# 找到可用的系统 Node 时返回 0。
system_node_ok() {
  have node || return 1
  v="$(node --version 2>/dev/null | sed 's/^v//; s/\..*//')"
  [ -n "$v" ] && [ "$v" -ge "$MIN_NODE_MAJOR" ] 2>/dev/null
}

# 从国内镜像解析最新 v22 LTS 版本字符串（如 v22.20.0），无需 jq/Python；
# 索引不可达时回退到固定版本。
latest_node_v22() {
  idx="$(curl -fsSL "$PICO_NODE_MIRROR/index.json" 2>/dev/null || true)"
  ver="$(printf '%s' "$idx" | tr ',' '\n' | grep -o '"version":"v22\.[0-9.]*"' \
         | head -n1 | sed 's/.*"v/v/; s/"$//')"
  [ -n "$ver" ] && printf '%s' "$ver" || printf 'v22.20.0'
}

# 输出 Pico 配置的首个私有 Node 二进制路径；不存在时返回非零。遍历 glob 可避免
# 多个版本目录残留时向 `[ -x ... ]` 传入多个参数而报错。
private_node_bin() {
  for n in "$NODE_RUNTIME_DIR"/node-v22*/bin/node; do
    [ -x "$n" ] || continue
    # 必须实际运行一次：解压不完整或损坏的二进制可能有执行权限却无法运行，
    # 不能误判为就绪运行时，否则永远不会重新下载。
    "$n" --version >/dev/null 2>&1 && { printf '%s' "$n"; return 0; }
  done
  return 1
}

ensure_node() {
  if system_node_ok; then
    ok "Node.js already meets requirement ($(node --version))"
    return
  fi
  # 检查先前运行是否已经私有配置。
  if pn="$(private_node_bin)"; then
    ok "Pico private Node already present ($pn)"
    return
  fi

  info "Node.js >= $MIN_NODE_MAJOR not found; downloading a private runtime (does not touch the system)..."
  ver="$(latest_node_v22)"
  pkg="node-${ver}-${NODE_OS}-${NODE_ARCH}"
  url="$PICO_NODE_MIRROR/${ver}/${pkg}.tar.gz"
  mkdir -p "$NODE_RUNTIME_DIR"
  tmp="$(mktemp -d)"
  info "  $url"
  curl -fsSL "$url" -o "$tmp/node.tar.gz" || die "Node download failed: $url"

  # 供应链完整性：压缩包走国内镜像，摘要默认从 Node.js 上游独立获取。
  curl -fsSL "$PICO_NODE_CHECKSUM_BASE/${ver}/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt" \
    || die "Could not fetch Node SHASUMS256.txt"
  expected="$(awk -v f="${pkg}.tar.gz" '$2==f {print $1}' "$tmp/SHASUMS256.txt")"
  [ -n "$expected" ] || die "SHASUMS256.txt did not list ${pkg}.tar.gz"
  if have shasum; then
    actual="$(shasum -a 256 "$tmp/node.tar.gz" | awk '{print $1}')"
  elif have sha256sum; then
    actual="$(sha256sum "$tmp/node.tar.gz" | awk '{print $1}')"
  else
    die "shasum or sha256sum is required to verify Node"
  fi
  if [ "$actual" != "$expected" ]; then
    die "Node checksum mismatch (expected $expected, got $actual)"
  fi
  ok "Node tarball SHA256 verified"

  tar -xzf "$tmp/node.tar.gz" -C "$NODE_RUNTIME_DIR"
  rm -rf "$tmp"
  [ -x "$NODE_RUNTIME_DIR/$pkg/bin/node" ] || die "Node executable not found after extraction"
  # 立即运行一次，在安装阶段发现 libc 不匹配（如 Alpine/musl 使用 glibc 包），
  # 避免之后才让用户机器上的 `pico` 失败。
  "$NODE_RUNTIME_DIR/$pkg/bin/node" --version >/dev/null 2>&1 \
    || die "Downloaded Node cannot run on this machine (possible libc mismatch, e.g. Alpine/musl). Install Node >= ${MIN_NODE_MAJOR} via your system package manager."
  ok "Node private runtime ready: $NODE_RUNTIME_DIR/$pkg"
  # Pico 的 find_node() 会自动匹配 ~/.pico/runtime/node-*/bin/node，因此无需
  # 修改 PATH。
}

# --- 3. 安装 Pico ----------------------------------------------------------
# Checkout 内没有 TUI bundle 且存在可用 Node 时现场构建；该产物被 Git 忽略，
# 缺失时安装后的 `pico` 无法启动。
build_tui_if_needed() {
  checkout_dir="$1"
  [ -f "$checkout_dir/ui-tui/dist/entry.js" ] && return 0
  node_bin="$(command -v node || true)"
  [ -n "$node_bin" ] || node_bin="$(private_node_bin || true)"
  if [ -n "$node_bin" ] && [ -x "$node_bin" ]; then
    node_dir="$(dirname "$node_bin")"
    # npm 随 Node 一起发布，但使用前仍需显式验证。
    if PATH="$node_dir:$PATH" command -v npm >/dev/null 2>&1; then
      info "Building the TUI bundle (ui-tui/dist/entry.js)..."
      ( cd "$checkout_dir/ui-tui" && PATH="$node_dir:$PATH" npm ci --registry "$PICO_NPM_REGISTRY" && PATH="$node_dir:$PATH" npm run build )
    else
      warn "Found node but not npm; skipping TUI build; pico may not work"
    fi
  else
    warn "No usable node found; skipping TUI build; pico may not work"
  fi
}

install_pico() {
  # 本地模式：在 Pico 源码检出内运行时，按开发者预期以可编辑模式安装工作树；
  # 远程模式：从 GitHub 克隆源码，构建 TUI 后以非可编辑模式安装。
  script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
  if [ -f "$script_dir/pyproject.toml" ] && grep -q '^name = "pico-harness"' "$script_dir/pyproject.toml" 2>/dev/null; then
    info "Local Pico source detected; editable install: $script_dir"
    build_tui_if_needed "$script_dir"
    install_result=0
    UV_DEFAULT_INDEX="$PICO_PYPI_INDEX" uv tool install --force -e "$script_dir[channels]" || install_result=$?
    if [ "$install_result" -ne 0 ]; then
      warn "Channel dependencies failed to install; installed base pico only. Some channels stay unavailable (see: pico channels list)."
      UV_DEFAULT_INDEX="$PICO_PYPI_INDEX" uv tool install --force -e "$script_dir"
    fi
  elif [ -n "${PICO_WHEEL_URL:-}" ]; then
    # 固定制品：直接安装维护者提供并经过信任的 wheel。
    wheel_source="$PICO_WHEEL_URL"
    info "  installing $wheel_source"
    install_result=0
    UV_DEFAULT_INDEX="$PICO_PYPI_INDEX" uv tool install --force "pico-harness[channels] @ $wheel_source" || install_result=$?
    if [ "$install_result" -ne 0 ]; then
      warn "Channel dependencies failed to install; installed base pico only. Some channels stay unavailable (see: pico channels list)."
      UV_DEFAULT_INDEX="$PICO_PYPI_INDEX" uv tool install --force "$wheel_source"
    fi
  else
    have git || die "git is required to clone Pico; install git or set PICO_WHEEL_URL to a trusted wheel."
    src_dir="$PICO_HOME/src/pico-harness"
    if [ -d "$src_dir/.git" ]; then
      info "Updating the existing Pico checkout at $src_dir..."
      git -C "$src_dir" pull --ff-only \
        || warn "git pull failed; continuing with the existing checkout at $src_dir"
    else
      info "Cloning $PICO_REPO_URL..."
      mkdir -p "$PICO_HOME/src"
      git clone --depth 1 "$PICO_REPO_URL" "$src_dir"
    fi
    build_tui_if_needed "$src_dir"
    install_result=0
    UV_DEFAULT_INDEX="$PICO_PYPI_INDEX" uv tool install --force "$src_dir[channels]" || install_result=$?
    if [ "$install_result" -ne 0 ]; then
      warn "Channel dependencies failed to install; installed base pico only. Some channels stay unavailable (see: pico channels list)."
      UV_DEFAULT_INDEX="$PICO_PYPI_INDEX" uv tool install --force "$src_dir"
    fi
  fi
  # 确保后续 shell 的 PATH 包含 uv 工具目录 ~/.local/bin。
  uv tool update-shell || true
  ok "Pico installed"
}

# --- 主流程 ----------------------------------------------------------------
main() {
  have curl || die "curl is required; please install it first"
  detect_platform
  ensure_uv
  ensure_node
  install_pico

  printf '\n'
  ok "All set! Open a new terminal (or source your shell profile), enter a Git repository, then run:"
  printf '\n    \033[1mpico onboard --skip-memory\033[0m    # configure Provider and first Turn\n'
  printf '    \033[1mpico\033[0m            # enter the TUI\n'
  printf '    \033[1mpico run\033[0m -m "hello"\n\n'
  if ! printf '%s' "$PATH" | grep -q "$HOME/.local/bin"; then
    warn "Your current PATH does not include ~/.local/bin yet -- open a new terminal, or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
}

main "$@"
