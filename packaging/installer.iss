; Inno Setup script for vjson Studio 3D.
; Build after PyInstaller:  ISCC packaging\installer.iss   ->  dist\vjson-Studio-3D-Setup-<version>.exe
; Installs per user by default (no admin needed); choose "all users" in the wizard to install machine-wide.

#define AppName "vjson Studio 3D"
#define AppVersion "0.1.0"
#define AppPublisher "Vaibhav H"
#define AppURL "https://github.com/vaibhav-1509/ijewel-vjson-studio"
#define AppExe "vjson Studio 3D.exe"

[Setup]
AppId={{6E0C2C4B-6F5E-4B0B-9C3E-1F7A2D9E5B41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=vjson-Studio-3D-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assocvjson"; Description: "Open .vjson files with {#AppName}"; GroupDescription: "File types:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.vjson\OpenWithProgids"; ValueType: string; ValueName: "vjsonStudio3D.vjson"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocvjson
Root: HKA; Subkey: "Software\Classes\vjsonStudio3D.vjson"; ValueType: string; ValueName: ""; ValueData: "iJewel3D scene"; Flags: uninsdeletekey; Tasks: assocvjson
Root: HKA; Subkey: "Software\Classes\vjsonStudio3D.vjson\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assocvjson
Root: HKA; Subkey: "Software\Classes\vjsonStudio3D.vjson\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assocvjson

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
