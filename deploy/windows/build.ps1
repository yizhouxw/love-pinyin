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
& $csc /nologo /codepage:65001 /target:winexe /platform:x64 /reference:System.Windows.Forms.dll "/out:$launcher" deploy/windows/Launcher.cs
& (Join-Path $bundle 'python/python.exe') deploy/windows/smoke.py
$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
$innoVersion = (Get-Item $iscc).VersionInfo.ProductVersion
if ($innoVersion -notmatch '^6\.7\.1(?:\.|$)') { throw "Expected Inno Setup 6.7.1, found $innoVersion" }
& $iscc deploy/windows/installer.iss
$installer = Join-Path $output 'LovePinyin-windows-x64-setup.exe'
$hash = (Get-FileHash -Algorithm SHA256 $installer).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$installer.sha256", "$hash  LovePinyin-windows-x64-setup.exe`n")
