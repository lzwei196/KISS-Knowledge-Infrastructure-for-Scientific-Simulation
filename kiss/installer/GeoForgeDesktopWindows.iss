#ifndef AppVersion
  #define AppVersion "0.6.57"
#endif
#ifndef SourceDir
  #error SourceDir must point to the packaged "GeoForge Desktop <version> Windows" folder
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

#define AppName "GeoForge Desktop"
#define AppExe "GeoForge Desktop.exe"
#define AppPublisher "KISS — Knowledge Infrastructure for Scientific Simulation"
#define AppUrl "https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation"

[Setup]
AppId={{7E81E664-31FA-4D50-A606-980056B3D08A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={localappdata}\Programs\GeoForge Desktop
DefaultGroupName=GeoForge Desktop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=GeoForge-Desktop-Setup-v{#AppVersion}-Windows-x64
SetupIconFile=..\..\assets\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=GeoForge Desktop Windows installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GeoForge Desktop"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\GeoForge Desktop"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,GeoForge Desktop}"; Flags: nowait postinstall skipifsilent
