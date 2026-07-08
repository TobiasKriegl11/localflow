; Inno Setup script for LocalFlow — SLIM edition (~100 MB).
; Ships the app without the models; LocalFlow downloads them (~1 GB, once)
; with a progress window on first launch. Ideal for sending to friends/family.
; Build: ISCC.exe installer\localflow_slim.iss  (after PyInstaller build)

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
OutputBaseFilename=LocalFlow-Setup-Slim-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Files]
; Same payload as the full installer minus the models directory.
Source: "..\dist\LocalFlow\*"; DestDir: "{app}"; \
    Excludes: "models\*"; Flags: recursesubdirs ignoreversion

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
; Downloaded models live under {app}\models and are removed with the app dir.
Type: filesandordirs; Name: "{userappdata}\LocalFlow"
