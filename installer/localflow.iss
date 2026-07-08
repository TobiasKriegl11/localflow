; Inno Setup script for LocalFlow.
; Build: ISCC.exe installer\localflow.iss  (after PyInstaller build + models staged)

#define AppName "LocalFlow"
#define AppVersion "0.1.0"
#define AppExe "LocalFlow.exe"

[Setup]
AppId={{6F1B3A5E-9C2D-4E7A-B1F4-LOCALFLOW001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=LocalFlow
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=LocalFlow-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Files]
Source: "..\dist\LocalFlow\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startlogin"; Description: "Start LocalFlow when you sign in"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"""; \
    Flags: uninsdeletevalue; Tasks: startlogin

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\LocalFlow"
