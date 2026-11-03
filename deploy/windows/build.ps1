$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Join-Path $PSScriptRoot '../..')
if (-not $IsWindows) { throw 'Windows is required' }
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'x64 Windows is required' }
$output = Join-Path (Get-Location) 'build/windows'
if (Test-Path $output) { Remove-Item -Recurse -Force $output }
$bundle = Join-Path $output 'app'
$resources = Join-Path $bundle 'app'
New-Item -ItemType Directory -Force $resources | Out-Null
npm ci --no-audit --no-fund
npm run build
uv python install 3.12.12
Push-Location $env:TEMP
try { $python = (uv python find --no-project --managed-python 3.12.12).Trim() } finally { Pop-Location }
$pythonRoot = Split-Path $python
Copy-Item -Recurse $pythonRoot (Join-Path $bundle 'python')
uv export --locked --no-default-groups --no-emit-project --quiet -o (Join-Path $output 'requirements.txt')
uv pip install --break-system-packages --python (Join-Path $bundle 'python/python.exe') --requirements (Join-Path $output 'requirements.txt')
foreach ($item in @('server','scripts','content','resources','dist')) { Copy-Item -Recurse $item $resources }
New-Item -ItemType Directory -Force (Join-Path $resources 'private') | Out-Null
Copy-Item -Recurse 'private/pinyinsound' (Join-Path $resources 'private/pinyinsound')
Copy-Item LICENSE,THIRD_PARTY_NOTICES.md $resources
Get-ChildItem $resources -Directory -Recurse -Filter '__pycache__' | Remove-Item -Recurse -Force
$csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$launcher = Join-Path $bundle 'LovePinyin.exe'
& $csc /nologo /codepage:65001 /target:winexe /platform:x64 /reference:System.Windows.Forms.dll "/out:$launcher" "/win32icon:$(Join-Path $PSScriptRoot 'AppIcon.ico')" (Join-Path $PSScriptRoot 'Launcher.cs')
& (Join-Path $bundle 'python/python.exe') deploy/windows/smoke.py
$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
$innoVersion = (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1').DisplayVersion
if ($innoVersion -notmatch '^6\.7\.1(?:\.|$)') { throw "Expected Inno Setup 6.7.1, found $innoVersion" }
& $iscc deploy/windows/installer.iss
$installer = Join-Path $output 'LovePinyin-windows-x64-setup.exe'
$testBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$testInstall = Join-Path $testBase 'LovePinyin-install-smoke'
if (Test-Path $testInstall) { throw "Test install directory already exists: $testInstall" }
$installed = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$testInstall`"") -Wait -PassThru
if ($installed.ExitCode -ne 0) { throw "Installer failed: $($installed.ExitCode)" }
try {
    & (Join-Path $testInstall 'python/python.exe') deploy/windows/smoke.py $testInstall
} finally {
    $uninstaller = Join-Path $testInstall 'unins000.exe'
    if (Test-Path $uninstaller) { Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait }
}
$hash = (Get-FileHash -Algorithm SHA256 $installer).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$installer.sha256", "$hash  LovePinyin-windows-x64-setup.exe`n")
