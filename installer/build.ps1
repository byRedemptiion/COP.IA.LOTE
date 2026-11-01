# Construit dist\ALICIA-Setup.exe (lancé par GitHub Actions sur Windows, ou à la main).
# Prérequis : Inno Setup 6 (choco install innosetup). Télécharge uv pour l'embarquer.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force build | Out-Null

# uv : le gestionnaire Python embarqué dans l'installateur
$zip = "build\uv.zip"
Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip
Expand-Archive $zip -DestinationPath "build\uv" -Force
Copy-Item "build\uv\uv.exe" "build\uv.exe" -Force

# Version installée : le bouton MAJ compare ce commit au dernier de la branche suivie
$sha = $env:GITHUB_SHA
if (-not $sha) { $sha = (git rev-parse HEAD) }
$branch = $env:ALICIA_BRANCH
if (-not $branch) { $branch = "alice-v0.3" }
$date = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
Set-Content "build\.alicia-version" "{`"sha`": `"$sha`", `"branch`": `"$branch`", `"date`": `"$date`"}" -NoNewline -Encoding ASCII

$version = (Select-String -Path "..\pyproject.toml" -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
$appVersion = "$version-$($sha.Substring(0, 7))"

$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "ISCC.exe" }
$output = & $iscc "/DAppVersion=$appVersion" "alicia.iss" 2>&1
$code = $LASTEXITCODE
$output | ForEach-Object { Write-Host $_ }
if ($code -ne 0) {
    # Les erreurs remontent en annotations GitHub (lisibles sans ouvrir le journal complet).
    $output | Select-Object -Last 25 | ForEach-Object { Write-Host "::error title=ISCC::$_" }
    exit $code
}
Write-Host "Installateur prêt : dist\ALICIA-Setup.exe ($appVersion)"
