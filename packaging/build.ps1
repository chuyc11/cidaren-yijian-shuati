$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
python -m PyInstaller --noconfirm Easy_Cidaren_Fixed.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Write-Host 'Build complete: dist\Easy_Cidaren_Fixed\Easy_Cidaren_Fixed.exe'
