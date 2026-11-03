#define MyAppName "爱拼音"
#define MyAppVersion "0.6.1"
[Setup]
AppId={{26AF9A06-6C12-4893-9F59-908F75E8E003}
SetupIconFile=AppIcon.ico
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\LovePinyin
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\build\windows
OutputBaseFilename=LovePinyin-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
[Files]
Source: "..\..\build\windows\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\爱拼音"; Filename: "{app}\LovePinyin.exe"
Name: "{autodesktop}\爱拼音"; Filename: "{app}\LovePinyin.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; Flags: unchecked
[Run]
Filename: "{app}\LovePinyin.exe"; Description: "启动爱拼音"; Flags: nowait postinstall skipifsilent
