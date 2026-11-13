# Build dist\Pyde with PyInstaller and zip it as dist\Pyde-<version>-windows-x64.zip.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

$version = uv version --short
$zip = "dist\Pyde-$version-windows-x64.zip"

# Clear out earlier builds.
Remove-Item -Recurse -Force build, dist\Pyde, dist\Pyde-*.zip -ErrorAction SilentlyContinue
uv run pyinstaller pyde.spec --noconfirm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# The zip holds one folder, Pyde, with Pyde.exe inside it.
Compress-Archive -Path dist\Pyde -DestinationPath $zip

Write-Output "Built $zip"
