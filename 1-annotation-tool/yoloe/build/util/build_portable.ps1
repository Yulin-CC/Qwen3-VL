# Build a portable Grounding review zip (embedded Python + app).
# Prefer: double-click ..\一键打包.bat
#
# Fast path when build\runtime already exists:
#   - skip pip if imports already ok
#   - robocopy runtime (many small files)
#   - zip via tar -a or .NET Fastest (not Compress-Archive Optimal)
#
# Options:
#   -SkipPythonInstall   reuse existing build\runtime\python
#   -ForcePip            always re-run pip install
#   -SkipZip             assemble dist only
#   -PythonVersion 3.12.13
#   -StandaloneTag 20260805
#   -VersionTag v0.3.3

param(
  [string]$PythonVersion = "3.12.13",
  [string]$StandaloneTag = "20260805",
  [switch]$SkipPythonInstall,
  [switch]$ForcePip,
  [switch]$SkipZip,
  [string]$VersionTag = "v0.5.6"
)

$ErrorActionPreference = "Stop"
$swTotal = [System.Diagnostics.Stopwatch]::StartNew()

# this script lives in yoloe\build\util\
$BuildUtilDir = $PSScriptRoot
$BuildRoot = Split-Path -Parent $BuildUtilDir
$YoloeRoot = Split-Path -Parent $BuildRoot

$RuntimePy = Join-Path $BuildRoot "runtime\python"
$RuntimeExe = Join-Path $RuntimePy "python.exe"
$DistRoot = Join-Path $BuildRoot "0-dist"
$BundleName = "GroundingReview-portable"
$BundleDir = Join-Path $DistRoot $BundleName
$CacheDir = Join-Path $BuildRoot "cache"
# build\使用说明.txt：按扩展名定位，避免中文路径编码坑
$ReadmeCnName = -join ([char]0x4F7F, [char]0x7528, [char]0x8BF4, [char]0x660E) + ".txt"
$UserReadme = $null
$readmeHit = Get-ChildItem -LiteralPath $BuildRoot -File -Filter "*.txt" -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -eq $ReadmeCnName -or $_.BaseName -match "说明|readme|使用" } |
  Select-Object -First 1
if (-not $readmeHit) {
  $readmeHit = Get-ChildItem -LiteralPath $BuildRoot -File -Filter "*.txt" -ErrorAction SilentlyContinue |
    Select-Object -First 1
}
if ($readmeHit) { $UserReadme = $readmeHit.FullName }
$StartPortable = Join-Path $BuildUtilDir "start_portable.bat"

$AssetName = "cpython-$PythonVersion+$StandaloneTag-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$AssetPath = Join-Path $CacheDir $AssetName
$DownloadUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$StandaloneTag/$AssetName"

Write-Host "== Grounding portable build =="
Write-Host "  yoloe:   $YoloeRoot"
Write-Host "  build:   $BuildRoot"
Write-Host "  runtime: $RuntimePy"
Write-Host "  dist:    $BundleDir"
Write-Host "  python:  $AssetName"
Write-Host ""

function Assert-Runtime([string]$pyExe) {
  & $pyExe -c "import tkinter; import flask; import PIL; import tqdm; import requests; print('ok', flush=True)"
  return ($LASTEXITCODE -eq 0)
}

function Copy-TreeFast([string]$src, [string]$dst) {
  # robocopy is much faster than Copy-Item for many small files
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  & robocopy $src $dst /E /NFL /NDL /NJH /NJS /NC /NS /NP /R:1 /W:1 | Out-Null
  $code = $LASTEXITCODE
  # robocopy: 0-7 = success with various copy stats
  if ($code -ge 8) {
    throw "robocopy failed ($code): $src -> $dst"
  }
}

function Remove-TreeFast([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) { return }
  # rmdir is faster than Remove-Item -Recurse on huge trees
  cmd /c "rmdir /s /q `"$path`""
  if (Test-Path -LiteralPath $path) {
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function New-ZipFast([string]$sourceDir, [string]$zipPath) {
  if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
  }

  # Prefer .NET Fastest: ~2s vs tar ~45s / Compress-Archive Optimal on this tree
  # Zip slightly larger (~29MB vs ~27MB) — worth it for rebuild speed.
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [System.IO.Compression.ZipFile]::CreateFromDirectory(
    $sourceDir, $zipPath,
    [System.IO.Compression.CompressionLevel]::Fastest,
    $true
  )
  if (Test-Path -LiteralPath $zipPath) {
    return "dotnet-fastest"
  }

  # Fallback: 7-Zip low compression
  $seven = @(
    "${env:ProgramFiles}\7-Zip\7z.exe",
    "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($seven) {
    & $seven a -tzip -mx=1 $zipPath "$sourceDir\*" | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $zipPath)) {
      return "7z"
    }
  }

  # Last resort: tar -a
  $parent = Split-Path -Parent $sourceDir
  $leaf = Split-Path -Leaf $sourceDir
  Push-Location $parent
  try {
    & tar -a -c -f $zipPath $leaf
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $zipPath)) {
      return "tar"
    }
  } finally {
    Pop-Location
  }
  throw "zip failed: $zipPath"
}

function Install-StandalonePython {
  New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
  if (-not (Test-Path -LiteralPath $AssetPath)) {
    Write-Host "Downloading $DownloadUrl ..."
    Write-Host "(first time ~30-50MB, please wait)"
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $AssetPath
  } else {
    Write-Host "Using cached: $AssetPath"
  }

  $extractTmp = Join-Path $CacheDir "standalone-extract"
  Remove-TreeFast $extractTmp
  New-Item -ItemType Directory -Force -Path $extractTmp | Out-Null

  Write-Host "Extracting standalone Python ..."
  tar -xzf $AssetPath -C $extractTmp
  if ($LASTEXITCODE -ne 0) { throw "tar extract failed" }

  $srcPy = Join-Path $extractTmp "python"
  if (-not (Test-Path -LiteralPath (Join-Path $srcPy "python.exe"))) {
    $found = Get-ChildItem -Path $extractTmp -Recurse -Filter "python.exe" |
      Where-Object { $_.DirectoryName -notmatch '\\Lib\\' } |
      Select-Object -First 1
    if (-not $found) { throw "python.exe not found in archive" }
    $srcPy = $found.DirectoryName
  }

  if (Test-Path -LiteralPath $RuntimePy) {
    Write-Host "Removing old runtime..."
    Remove-TreeFast $RuntimePy
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $RuntimePy) | Out-Null
  Write-Host "Installing -> build\runtime\python ..."
  Copy-TreeFast $srcPy $RuntimePy

  & $RuntimeExe -m ensurepip --upgrade 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "ensurepip missing, bootstrapping get-pip..."
    $getPip = Join-Path $CacheDir "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
    & $RuntimeExe $getPip
  }
}

# ---- 1) Python runtime ----
$needInstall = -not (Test-Path -LiteralPath $RuntimeExe)
if ($SkipPythonInstall -and -not $needInstall) {
  Write-Host "SkipPythonInstall: reuse $RuntimeExe"
} elseif ($needInstall) {
  Install-StandalonePython
} else {
  Write-Host "Runtime already present, skip download."
}

if (-not (Test-Path -LiteralPath $RuntimeExe)) {
  throw "python.exe missing: $RuntimeExe"
}

$depsOk = Assert-Runtime $RuntimeExe
if ($ForcePip -or -not $depsOk) {
  Write-Host "pip install flask pillow tqdm requests ..."
  & $RuntimeExe -m pip install --upgrade pip -q
  & $RuntimeExe -m pip install flask pillow tqdm requests -q
  if (-not (Assert-Runtime $RuntimeExe)) {
    throw "Runtime check failed (need tkinter + flask/pillow/tqdm/requests)."
  }
  Write-Host "Runtime OK (pip refreshed)."
} else {
  Write-Host "Runtime OK (deps already present, skip pip)."
}
Write-Host ""

# ---- 2) Assemble bundle ----
if (-not $UserReadme -or -not (Test-Path -LiteralPath $UserReadme)) {
  throw "missing template: build\*.txt (期望 使用说明.txt)"
}
if (-not (Test-Path -LiteralPath $StartPortable)) {
  throw "missing template: $StartPortable"
}
Write-Host "  readme:  $UserReadme"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
Remove-TreeFast $BundleDir
$YoloeOut = Join-Path $BundleDir "yoloe"
New-Item -ItemType Directory -Force -Path $YoloeOut | Out-Null

Write-Host "Copying runtime (robocopy)..."
$rtOut = Join-Path $YoloeOut "runtime\python"
Copy-TreeFast $RuntimePy $rtOut

Write-Host "Copying app files..."
Copy-TreeFast (Join-Path $YoloeRoot "util") (Join-Path $YoloeOut "util")
Copy-TreeFast (Join-Path $YoloeRoot "rules") (Join-Path $YoloeOut "rules")
$ModelDir = Join-Path $YoloeRoot "model"
if (Test-Path -LiteralPath $ModelDir) {
  Copy-TreeFast $ModelDir (Join-Path $YoloeOut "model")
}
Copy-Item -Path (Join-Path $YoloeRoot "1-start_review.bat") -Destination (Join-Path $YoloeOut "1-start_review.bat") -Force

# Annotation rules doc + screenshots (ASCII-only comments: PS5.1 encoding)
$ZOthers = Join-Path $YoloeRoot "z-others"
$ZOut = Join-Path $YoloeOut "z-others"
New-Item -ItemType Directory -Force -Path $ZOut | Out-Null
if (Test-Path -LiteralPath $ZOthers) {
  Get-ChildItem -LiteralPath $ZOthers -File -Filter "*.md" -ErrorAction SilentlyContinue |
    Where-Object {
      try {
        $head = Get-Content -LiteralPath $_.FullName -TotalCount 5 -Encoding UTF8 -ErrorAction Stop
        ($head -join "`n") -match "GroundingView"
      } catch { $false }
    } |
    ForEach-Object {
      Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $ZOut $_.Name) -Force
      Write-Host "  doc: $($_.Name)"
    }
  $PicDir = Join-Path $ZOthers "pic"
  if (Test-Path -LiteralPath $PicDir) {
    Copy-TreeFast $PicDir (Join-Path $ZOut "pic")
    Write-Host "  pic: z-others\pic"
  }
}

Copy-Item -LiteralPath $StartPortable -Destination (Join-Path $BundleDir "start.bat") -Force
Copy-Item -LiteralPath $UserReadme -Destination (Join-Path $BundleDir "README.txt") -Force

# drop caches from copied tree
Get-ChildItem -Path $BundleDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  ForEach-Object { Remove-TreeFast $_.FullName }

Write-Host ("Bundle assembled in {0:n1}s: {1}" -f $sw.Elapsed.TotalSeconds, $BundleDir)

# ---- 3) Zip ----
if (-not $SkipZip) {
  New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
  $ZipPath = Join-Path $DistRoot "$BundleName-$VersionTag.zip"
  Write-Host "Zipping -> $ZipPath ..."
  $sw.Restart()
  $engine = New-ZipFast $BundleDir $ZipPath
  $sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
  Write-Host ("Done via {0} in {1:n1}s. Zip size ~ {2} MB" -f $engine, $sw.Elapsed.TotalSeconds, $sizeMb)
  Write-Host "  $ZipPath"
} else {
  Write-Host "SkipZip: dist folder ready (no zip)."
}

Write-Host ""
Write-Host ("Total {0:n1}s. Give colleagues the zip; they unzip and double-click start.bat" -f $swTotal.Elapsed.TotalSeconds)
