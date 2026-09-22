# Pico 国内 Windows PowerShell 一键安装脚本。
#
# 远程：irm https://raw.githubusercontent.com/yangaobo0235/pico-harness/main/install.ps1 | iex
#
# 目标：让全新 Windows 机器无需管理员权限即可运行 `pico`。脚本具备幂等性，
# 会复用已有工具并只补齐缺项：
#   1. uv            （Python 工具链与包管理器）
#   2. Node.js >= 22 （TUI 运行时；系统缺少时私有安装）
#   3. pico          （作为全局 uv 工具安装）
#
# 远程模式从 GitHub 克隆源码并本地构建 TUI bundle；可用 PICO_REPO_URL 换源，
# 也可用 PICO_WHEEL_URL 直接安装经过信任的 wheel。

$ErrorActionPreference = "Stop"

$MinNodeMajor = 22
$PicoHome = if ($env:PICO_HOME) { $env:PICO_HOME } else { Join-Path $HOME ".pico" }
$NodeRuntimeDir = Join-Path $PicoHome "runtime"
$PicoRepoUrl = if ($env:PICO_REPO_URL) { $env:PICO_REPO_URL } else { "https://github.com/yangaobo0235/pico-harness.git" }
$PicoNodeMirror = if ($env:PICO_NODE_MIRROR) { $env:PICO_NODE_MIRROR.TrimEnd('/') } else { "https://mirrors.aliyun.com/nodejs-release" }
$PicoNodeChecksumBase = if ($env:PICO_NODE_CHECKSUM_BASE) { $env:PICO_NODE_CHECKSUM_BASE.TrimEnd('/') } else { "https://nodejs.org/dist" }
$PicoNpmRegistry = if ($env:PICO_NPM_REGISTRY) { $env:PICO_NPM_REGISTRY } else { "https://registry.npmmirror.com" }
$PicoPyPIIndex = if ($env:PICO_PYPI_INDEX) { $env:PICO_PYPI_INDEX } else { "https://pypi.tuna.tsinghua.edu.cn/simple" }
$PicoUvInstallUrl = if ($env:PICO_UV_INSTALL_URL) { $env:PICO_UV_INSTALL_URL } else { "https://astral.sh/uv/install.ps1" }

function Write-Info([string]$Message) {
    Write-Host ">" $Message -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "OK" $Message -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Warning $Message
}

function Fail([string]$Message) {
    Write-Error $Message
    exit 1
}

function Add-ProcessPath([string]$PathToAdd) {
    if (-not $PathToAdd) { return }
    if (-not (Test-Path $PathToAdd)) { return }
    $parts = $env:PATH -split ';'
    if ($parts -notcontains $PathToAdd) {
        $env:PATH = "$PathToAdd;$env:PATH"
    }
}

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        (Join-Path $HOME ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Ensure-Uv {
    $uv = Find-Uv
    if ($uv) {
        Write-Ok "uv is installed ($(& $uv --version))"
        Add-ProcessPath (Split-Path $uv -Parent)
        return $uv
    }

    Write-Info "uv not found; installing..."
    Invoke-Expression (Invoke-RestMethod $PicoUvInstallUrl)
    $uv = Find-Uv
    if (-not $uv) {
        Fail "uv was installed but is still not available. Check PATH (expected ~/.local/bin)."
    }
    Add-ProcessPath (Split-Path $uv -Parent)
    Write-Ok "uv installed"
    return $uv
}

function Get-NodeArch {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "ARM64" { return "arm64" }
        "AMD64" { return "x64" }
        default { Fail "Unsupported Windows architecture: $env:PROCESSOR_ARCHITECTURE" }
    }
}

function Test-NodeOk([string]$NodePath) {
    if (-not $NodePath) { return $false }
    if (-not (Test-Path $NodePath)) { return $false }
    try {
        $version = (& $NodePath --version).Trim()
        $major = [int](($version.TrimStart("v") -split "\.")[0])
        return $major -ge $MinNodeMajor
    } catch {
        return $false
    }
}

function Find-PrivateNode {
    $candidates = @()
    $direct = Join-Path $NodeRuntimeDir "node\node.exe"
    $directBin = Join-Path $NodeRuntimeDir "node\bin\node.exe"
    if (Test-Path $direct) { $candidates += $direct }
    if (Test-Path $directBin) { $candidates += $directBin }
    if (Test-Path $NodeRuntimeDir) {
        $candidates += Get-ChildItem $NodeRuntimeDir -Directory -Filter "node-v22*" -ErrorAction SilentlyContinue |
            ForEach-Object {
                @(
                    (Join-Path $_.FullName "node.exe"),
                    (Join-Path $_.FullName "bin\node.exe")
                )
            }
    }
    foreach ($candidate in $candidates) {
        if (Test-NodeOk $candidate) { return $candidate }
    }
    return $null
}

function Get-LatestNodeV22 {
    try {
        $index = Invoke-RestMethod "$PicoNodeMirror/index.json"
        $entry = $index | Where-Object { $_.version -like "v22.*" } | Select-Object -First 1
        if ($entry -and $entry.version) { return $entry.version }
    } catch {
        Write-Warn "Could not query Node.js release index; falling back to v22.20.0"
    }
    return "v22.20.0"
}

function Ensure-Node {
    $systemNode = Get-Command node -ErrorAction SilentlyContinue
    if ($systemNode -and (Test-NodeOk $systemNode.Source)) {
        Write-Ok "Node.js meets requirements ($(& $systemNode.Source --version))"
        return $systemNode.Source
    }

    $privateNode = Find-PrivateNode
    if ($privateNode) {
        Write-Ok "Existing Pico private Node found ($privateNode)"
        Add-ProcessPath (Split-Path $privateNode -Parent)
        return $privateNode
    }

    Write-Info "Node.js >= $MinNodeMajor not found; downloading private runtime..."
    $arch = Get-NodeArch
    $version = Get-LatestNodeV22
    $pkg = "node-$version-win-$arch"
    $url = "$PicoNodeMirror/$version/$pkg.zip"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("pico-node-" + [guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $tmp "node.zip"

    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    New-Item -ItemType Directory -Path $NodeRuntimeDir -Force | Out-Null

    try {
        Write-Info "  $url"
        Invoke-WebRequest $url -OutFile $zipPath

        try {
            $sums = (Invoke-WebRequest "$PicoNodeChecksumBase/$version/SHASUMS256.txt").Content
        } catch {
            Fail "Could not fetch Node SHASUMS256.txt: $_"
        }
        $line = ($sums -split "`n") | Where-Object { $_ -match "\s+$([regex]::Escape("$pkg.zip"))$" } | Select-Object -First 1
        if (-not $line) {
            Fail "SHASUMS256.txt did not list $pkg.zip."
        }
        $expected = (($line.Trim()) -split "\s+")[0].ToLowerInvariant()
        $actual = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($expected -ne $actual) {
            Fail "Node checksum mismatch (expected $expected, got $actual)."
        }
        Write-Ok "Node zip SHA256 verified"

        Expand-Archive $zipPath -DestinationPath $tmp -Force
        $src = Join-Path $tmp $pkg
        $dest = Join-Path $NodeRuntimeDir $pkg
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Move-Item $src $dest

        $node = Join-Path $dest "node.exe"
        if (-not (Test-NodeOk $node)) {
            Fail "Downloaded Node runtime is not usable on this machine."
        }
        Add-ProcessPath $dest
        Write-Ok "Node private runtime ready: $dest"
        return $node
    } finally {
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Build-TuiBundle([string]$CheckoutDir) {
    # Checkout 内没有 TUI bundle 时现场构建；该产物被 Git 忽略，
    # 缺失时安装后的 `pico` 无法启动。系统 Node 优先，其次私有 Node。
    $entry = Join-Path $CheckoutDir "ui-tui\dist\entry.js"
    if (Test-Path $entry) { return }
    $node = $null
    $systemNode = Get-Command node -ErrorAction SilentlyContinue
    if ($systemNode -and (Test-NodeOk $systemNode.Source)) { $node = $systemNode.Source }
    if (-not $node) { $node = Find-PrivateNode }
    if (-not $node) {
        Write-Warn "No usable node found; skipping TUI build; pico may not work"
        return
    }
    Add-ProcessPath (Split-Path $node -Parent)
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Warn "Found node but not npm; skipping TUI build; pico may not work"
        return
    }
    Write-Info "Building the TUI bundle (ui-tui/dist/entry.js)..."
    Push-Location (Join-Path $CheckoutDir "ui-tui")
    try {
        & $npm.Source ci --registry $PicoNpmRegistry
        & $npm.Source run build
    } finally {
        Pop-Location
    }
}

function Install-FromCheckout([string]$UvPath, [string]$DirPath, [switch]$Editable) {
    $previousIndex = $env:UV_DEFAULT_INDEX
    $env:UV_DEFAULT_INDEX = $PicoPyPIIndex
    try {
        if ($Editable) {
            & $UvPath tool install --force -e "$DirPath[channels]"
        } else {
            & $UvPath tool install --force "$DirPath[channels]"
        }
        if ($LASTEXITCODE -ne 0) { throw "channel extras install failed" }
    } catch {
        Write-Warn "Channel dependencies failed to install; installed base pico only. Some channels stay unavailable (see: pico channels list)."
        if ($Editable) {
            & $UvPath tool install --force -e "$DirPath"
        } else {
            & $UvPath tool install --force $DirPath
        }
        if ($LASTEXITCODE -ne 0) { Fail "Pico install failed." }
    } finally {
        $env:UV_DEFAULT_INDEX = $previousIndex
    }
}

function Install-Pico([string]$UvPath, [string]$NodePath) {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $pyproject = Join-Path $scriptDir "pyproject.toml"
    if ((Test-Path $pyproject) -and (Select-String -Path $pyproject -Pattern '^name = "pico-harness"' -Quiet)) {
        Write-Info "Detected local Pico source checkout; installing editable: $scriptDir"
        Build-TuiBundle $scriptDir
        Install-FromCheckout $UvPath $scriptDir -Editable
    } elseif ($env:PICO_WHEEL_URL) {
        # 固定制品：直接安装维护者提供并经过信任的 wheel。
        $wheelSource = $env:PICO_WHEEL_URL
        Write-Info "  installing $wheelSource"
        $previousIndex = $env:UV_DEFAULT_INDEX
        $env:UV_DEFAULT_INDEX = $PicoPyPIIndex
        try {
            & $UvPath tool install --force "pico-harness[channels] @ $wheelSource"
            if ($LASTEXITCODE -ne 0) { throw "channel extras install failed" }
        } catch {
            Write-Warn "Channel dependencies failed to install; installed base pico only. Some channels stay unavailable (see: pico channels list)."
            & $UvPath tool install --force $wheelSource
            if ($LASTEXITCODE -ne 0) { Fail "Pico install failed." }
        } finally {
            $env:UV_DEFAULT_INDEX = $previousIndex
        }
    } else {
        # 远程模式：克隆（或更新）Pico HOME 下的长期源码检出，再非可编辑安装。
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Fail "git is required to clone Pico; install git or set PICO_WHEEL_URL to a trusted wheel."
        }
        $srcDir = Join-Path $PicoHome "src\pico-harness"
        if (Test-Path (Join-Path $srcDir ".git")) {
            Write-Info "Updating the existing Pico checkout at $srcDir..."
            & git -C $srcDir pull --ff-only
            if ($LASTEXITCODE -ne 0) { Write-Warn "git pull failed; continuing with the existing checkout at $srcDir" }
        } else {
            Write-Info "Cloning $PicoRepoUrl..."
            New-Item -ItemType Directory -Path (Join-Path $PicoHome "src") -Force | Out-Null
            & git clone --depth 1 $PicoRepoUrl $srcDir
            if ($LASTEXITCODE -ne 0) { Fail "git clone failed: $PicoRepoUrl" }
        }
        Build-TuiBundle $srcDir
        Install-FromCheckout $UvPath $srcDir
    }
    & $UvPath tool update-shell | Out-Null
    Write-Ok "Pico installed"
}

function Main {
    $uv = Ensure-Uv
    $node = Ensure-Node
    Install-Pico $uv $node

    $toolBin = Join-Path $HOME ".local\bin"
    Add-ProcessPath $toolBin

    Write-Host ""
    Write-Ok "All set. Open a new PowerShell window, enter a Git repository, then run:"
    Write-Host ""
    Write-Host "    pico onboard --skip-memory    # configure Provider and first Turn"
    Write-Host "    pico            # enter the TUI"
    Write-Host "    pico run -m `"hello`""
    Write-Host ""
    if (($env:PATH -split ';') -notcontains $toolBin) {
        Write-Warn "Current PATH does not include $toolBin. Restart PowerShell if 'pico' is not found."
    }
}

Main
