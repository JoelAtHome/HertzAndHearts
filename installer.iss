; Inno Setup script for Hertz & Hearts Windows installer.
; Expects the PyInstaller --onedir output in dist\Hertz-and-Hearts\.

#define MyAppName "Hertz-and-Hearts"
; MyAppVersion is passed via /DMyAppVersion="x.y.z" on the command line.
; Falls back to "1.0.0-beta.1" if not provided (e.g. local builds).
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0-beta.1"
#endif
#define MyAppPublisher "Hertz-and-Hearts"
#define MyAppExeName "Hertz-and-Hearts.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-AB12-CD34EF56AB78}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=Hertz-and-Hearts-Windows-Setup
SetupIconFile=docs\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Hertz-and-Hearts\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
