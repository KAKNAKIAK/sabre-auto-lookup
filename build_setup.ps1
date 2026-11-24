<#
build_setup.ps1
  세이버자동조회 EXE 빌드 + Windows 셋업 인스톨러 패키징 스크립트.
  버전은 sabre_updater.py의 APP_VERSION을 단일 기준으로 읽습니다.
#>
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$UpdaterPy = Join-Path $ProjectRoot "sabre_updater.py"
$IconPath = Join-Path $ProjectRoot "assets\sabre_icon.ico"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$PortableDir = Join-Path $ReleaseRoot "SabreAutoLookup"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$Version = ""
$updText = Get-Content -LiteralPath $UpdaterPy -Raw -Encoding UTF8
if ($updText -match 'APP_VERSION\s*=\s*"([^"]+)"') { $Version = $Matches[1] }
if (-not $Version) { throw "sabre_updater.py에서 APP_VERSION을 찾지 못했습니다." }
if (-not (Test-Path -LiteralPath $IconPath)) { throw "아이콘 파일이 없습니다: $IconPath" }

$SetupOut = Join-Path $ReleaseRoot "SabreAutoLookup_Setup_$Version.exe"
$SetupAlias = Join-Path $ReleaseRoot "SabreAutoLookup_Setup.exe"
$ShaOut = "$SetupOut.sha256"

function Reset-TempDir {
    param([Parameter(Mandatory = $true)][string]$Path)
    $TempRootFull = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\") + "\"
    $FullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $FullPath.StartsWith($TempRootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a non-temp path: $FullPath"
    }
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

Push-Location $ProjectRoot
try {
    # 외부 런타임(PATH) DLL(ucrtbase/icu 등) 혼입으로 인한 QtCore 로드 오류 방지
    $origPath = $env:PATH
    $env:PATH = (($env:PATH -split ';') | Where-Object { $_ -and ($_ -notmatch 'codex-runtimes') }) -join ';'
    Write-Host "[1/4] PyInstaller 확인 (버전: $Version)..."
    python -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller가 설치되어 있지 않습니다." }

    $AppExeName = "항공운임 조회 (SABRE VER.).exe"
    Write-Host "[2/4] $AppExeName 빌드 중..."
    $TempAppRoot = Join-Path ([System.IO.Path]::GetTempPath()) "SabreAutoLookupAppBuild"
    $TempAppDist = Join-Path $TempAppRoot "dist"
    $TempAppWork = Join-Path $TempAppRoot "build"
    Reset-TempDir -Path $TempAppRoot

    $appArgs = @(
        "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", $TempAppDist,
        "--workpath", $TempAppWork,
        (Join-Path $ProjectRoot "sabre_app.spec")
    )
    & python @appArgs
    if ($LASTEXITCODE -ne 0) { throw "$AppExeName 빌드 실패" }

    $BuiltExe = Join-Path $TempAppDist $AppExeName
    if (-not (Test-Path -LiteralPath $BuiltExe)) { throw "빌드된 EXE를 찾지 못했습니다: $BuiltExe" }

    New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $PortableDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $PortableDir "assets") | Out-Null
    $EmptyRoutesJson = '{"schema": "sabre-routes-v1", "routes": []}' + [Environment]::NewLine
    $SampleCsvSrc = Join-Path $ProjectRoot "sabre-routes.example.csv"
    $IconPngSrc = Join-Path $ProjectRoot "assets\sabre_icon.png"
    $IndexHtmlSrc = Join-Path $ProjectRoot "index.html"
    $ManualImgDir = Join-Path $ProjectRoot "docs\manual_images"
    try {
        Copy-Item -LiteralPath $BuiltExe -Destination (Join-Path $PortableDir $AppExeName) -Force -ErrorAction Stop
        Copy-Item -LiteralPath $IconPath -Destination (Join-Path $PortableDir "assets\sabre_icon.ico") -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $IconPngSrc) {
            Copy-Item -LiteralPath $IconPngSrc -Destination (Join-Path $PortableDir "assets\sabre_icon.png") -Force
        }
        if (Test-Path -LiteralPath $IndexHtmlSrc) {
            Copy-Item -LiteralPath $IndexHtmlSrc -Destination (Join-Path $PortableDir "index.html") -Force
        }
        if (Test-Path -LiteralPath $ManualImgDir) {
            $PortImgDir = Join-Path $PortableDir "docs\manual_images"
            New-Item -ItemType Directory -Force -Path $PortImgDir | Out-Null
            Copy-Item -Path "$ManualImgDir\*.png" -Destination $PortImgDir -Force
        }
        $PortRoutes = Join-Path $PortableDir "sabre-routes.json"
        if (-not (Test-Path -LiteralPath $PortRoutes)) {
            [System.IO.File]::WriteAllText($PortRoutes, $EmptyRoutesJson, $Utf8NoBom)
        }
        if (Test-Path -LiteralPath $SampleCsvSrc) {
            Copy-Item -LiteralPath $SampleCsvSrc -Destination (Join-Path $PortableDir "sabre-routes.example.csv") -Force
        }
    } catch {
        Write-Warning "실행 중인 EXE로 인해 release\SabreAutoLookup 갱신은 건너뜁니다. 셋업 패키징은 계속 진행합니다."
    }

    Write-Host "[3/4] 셋업 페이로드(payload.zip) 패키징 중..."
    $TempSetupRoot = Join-Path ([System.IO.Path]::GetTempPath()) "SabreAutoLookupSetupBuild"
    Reset-TempDir -Path $TempSetupRoot
    $PayloadDir = Join-Path $TempSetupRoot "payload"
    New-Item -ItemType Directory -Force -Path (Join-Path $PayloadDir "assets") | Out-Null

    Copy-Item -LiteralPath $BuiltExe -Destination (Join-Path $PayloadDir $AppExeName) -Force
    Copy-Item -LiteralPath $IconPath -Destination (Join-Path $PayloadDir "assets\sabre_icon.ico") -Force
    if (Test-Path -LiteralPath $IconPngSrc) {
        Copy-Item -LiteralPath $IconPngSrc -Destination (Join-Path $PayloadDir "assets\sabre_icon.png") -Force
    }
    if (Test-Path -LiteralPath $IndexHtmlSrc) {
        Copy-Item -LiteralPath $IndexHtmlSrc -Destination (Join-Path $PayloadDir "index.html") -Force
    }
    if (Test-Path -LiteralPath $ManualImgDir) {
        $PayImgDir = Join-Path $PayloadDir "docs\manual_images"
        New-Item -ItemType Directory -Force -Path $PayImgDir | Out-Null
        Copy-Item -Path "$ManualImgDir\*.png" -Destination $PayImgDir -Force
    }
    [System.IO.File]::WriteAllText((Join-Path $PayloadDir "sabre-routes.json"), $EmptyRoutesJson, $Utf8NoBom)
    if (Test-Path -LiteralPath $SampleCsvSrc) {
        Copy-Item -LiteralPath $SampleCsvSrc -Destination (Join-Path $PayloadDir "sabre-routes.example.csv") -Force
    }

    $PayloadZip = Join-Path $TempSetupRoot "payload.zip"
    Compress-Archive -Path "$PayloadDir\*" -DestinationPath $PayloadZip -Force

    Write-Host "[4/4] 셋업 인스톨러 EXE 빌드 중..."
    if (Test-Path -LiteralPath $SetupOut) { Remove-Item -LiteralPath $SetupOut -Force }

    $setupArgs = @(
        "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", "SabreAutoLookup_Setup_$Version",
        "--icon", $IconPath,
        "--distpath", $ReleaseRoot,
        "--workpath", (Join-Path $TempSetupRoot "build"),
        "--specpath", $TempSetupRoot,
        "--exclude-module", "PySide6",
        "--exclude-module", "openpyxl",
        "--exclude-module", "PIL",
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--add-data", "$PayloadZip;.",
        "--add-data", "$IconPath;.",
        (Join-Path $ProjectRoot "packaging\setup_installer.py")
    )
    & python @setupArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $SetupOut)) {
        throw "셋업 인스톨러 EXE 빌드 실패"
    }

    Copy-Item -LiteralPath $SetupOut -Destination $SetupAlias -Force
    $SetupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SetupOut).Hash.ToLowerInvariant()
    [System.IO.File]::WriteAllText($ShaOut, "$SetupHash  $(Split-Path -Leaf $SetupOut)" + [Environment]::NewLine, $Utf8NoBom)

    Write-Host "=========================================="
    Write-Host "빌드 및 셋업 패키징 완료 ($Version)"
    Write-Host "  포터블 EXE : $(Join-Path $PortableDir $AppExeName)"
    Write-Host "  셋업 파일  : $SetupOut"
    Write-Host "  셋업 별칭  : $SetupAlias"
    Write-Host "  SHA256     : $SetupHash"
    Write-Host "=========================================="
}
finally {
    if ($origPath) { $env:PATH = $origPath }
    Pop-Location
}
