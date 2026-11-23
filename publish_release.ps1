<#
publish_release.ps1
  세이버자동조회 빌드 + GitHub Release 배포 스크립트.
  사용예:
    .\publish_release.ps1
    .\publish_release.ps1 -Notes "단건 일정 조회 개선 및 최종 조회일 자동 탐색 추가"
    .\publish_release.ps1 -SkipBuild
#>
param(
    [string]$Version = "",
    [string]$Notes = "",
    [switch]$SkipBuild,
    [string]$Repo = "KAKNAKIAK/sabre-auto-lookup"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseRoot = Join-Path $ProjectRoot "release"

if (-not $Version) {
    $updText = Get-Content -LiteralPath (Join-Path $ProjectRoot "sabre_updater.py") -Raw -Encoding UTF8
    if ($updText -match 'APP_VERSION\s*=\s*"([^"]+)"') { $Version = $Matches[1] }
}
if (-not $Version) { throw "버전을 확인할 수 없습니다. sabre_updater.py의 APP_VERSION 또는 -Version을 확인하세요." }

if (-not $SkipBuild) {
    Write-Host "[publish] build_setup.ps1 실행 중..."
    & (Join-Path $ProjectRoot "build_setup.ps1")
    if ($LASTEXITCODE -ne 0) { throw "빌드 실패" }
}

$Setup = Join-Path $ReleaseRoot ("SabreAutoLookup_Setup_{0}.exe" -f $Version)
$ShaFile = "$Setup.sha256"
if (-not (Test-Path -LiteralPath $Setup)) {
    throw "셋업 파일이 없습니다: $Setup"
}
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Setup).Hash.ToLowerInvariant()
if (-not (Test-Path -LiteralPath $ShaFile)) {
    [System.IO.File]::WriteAllText($ShaFile, "$Hash  $(Split-Path -Leaf $Setup)" + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

$NL = [Environment]::NewLine
$Body = if ($Notes) { $Notes + $NL + $NL + "SHA256: " + $Hash } else { "항공운임 조회 (SABRE VER.) $Version 릴리즈" + $NL + $NL + "SHA256: " + $Hash }

$ErrorActionPreference = "Continue"
gh release view $Version --repo $Repo *> $null
$exists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"

if ($exists) {
    Write-Host "[publish] 기존 릴리즈($Version) 자산 갱신 중..."
    gh release upload $Version $Setup $ShaFile --repo $Repo --clobber
    gh release edit $Version --repo $Repo --notes $Body
} else {
    Write-Host "[publish] 새 GitHub 릴리즈($Version) 생성 및 업로드 중..."
    gh release create $Version $Setup $ShaFile --repo $Repo --title "항공운임 조회 (SABRE VER.) $Version" --notes $Body
}
if ($LASTEXITCODE -ne 0) { throw "GitHub 릴리즈 업로드 실패" }

Write-Host "=========================================="
Write-Host "GitHub 릴리즈 완료: $Repo ($Version)"
Write-Host "  셋업 파일: $Setup"
Write-Host "  SHA256   : $Hash"
Write-Host "=========================================="
