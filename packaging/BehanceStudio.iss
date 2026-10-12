; Inno Setup 6 script for Behance Studio (Windows 10/11, 64-bit).
; Built by build_windows.bat after PyInstaller has produced dist\BehanceStudio.
;
; * Installs per user by default (no administrator rights needed); an
;   administrator can choose "install for all users" in the first page.
; * Uninstalling removes the program folder only. Projects, settings, the
;   AI usage record and API keys (Windows Credential Manager) are kept.

#ifndef AppVersion
  #define AppVersion "2.0.0.dev1"
#endif
#ifndef NumericVersion
  #define NumericVersion "2.0.0.1"
#endif
#define AppName "Behance Studio"
#define AppExe "BehanceStudio.exe"

[Setup]
AppId={{6A0E5C1B-7F3D-4B9A-9E21-5D8C4B2F7A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#NumericVersion}
AppPublisher=Behance Studio
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\dist\installer
OutputBaseFilename=BehanceStudio-Setup-{#AppVersion}
SetupIconFile=..\src\behance_studio\resources\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\BehanceStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function EdgeInstalled(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe') or
            RegKeyExists(HKCU, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe') or
            FileExists(ExpandConstant('{commonpf32}\Microsoft\Edge\Application\msedge.exe')) or
            FileExists(ExpandConstant('{commonpf64}\Microsoft\Edge\Application\msedge.exe'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not EdgeInstalled() then
    MsgBox('Microsoft Edge was not found. Behance Studio uses Edge (or Google Chrome) in the background to render ' +
           'previews, PDFs and images. You can install it later; the app will tell you if no browser is available.',
           mbInformation, MB_OK);
end;
