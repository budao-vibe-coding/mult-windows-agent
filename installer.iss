; Inno Setup 编译器配置文件 - 支持 x64 / arm64 架构打包

#ifndef AppArch
  #define AppArch "x64"
#endif

[Setup]
AppName=Windows Multi-Agent Desktop App
AppVersion=1.0.0
AppPublisher=Budao Vibe Coding
DefaultDirName={autopf}\WindowsAuto
DefaultGroupName=WindowsAuto
AllowNoIcons=yes
OutputDir=Output
WizardStyle=modern

#if AppArch == "arm64"
  ; ARM64 专有配置
  OutputBaseFilename=WindowsAuto-Setup-arm64
  ArchitecturesAllowed=arm64
  ArchitecturesInstallIn64BitMode=arm64
#else
  ; x64 默认配置
  OutputBaseFilename=WindowsAuto-Setup-x64
  ArchitecturesAllowed=x64
  ArchitecturesInstallIn64BitMode=x64
#endif

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 打包后的主程序目录
Source: "dist\WindowsAuto\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\WindowsAuto"; Filename: "{app}\WindowsAuto.exe"
Name: "{autodesktop}\WindowsAuto"; Filename: "{app}\WindowsAuto.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WindowsAuto.exe"; Description: "{cm:LaunchProgram,WindowsAuto}"; Flags: nowait postinstall skipifsilent
