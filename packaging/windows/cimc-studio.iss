; The installer owns application files only. User exports and WebView2 data survive removal.
#ifndef AppVersion
  #define AppVersion "0.3.0"
#endif
#ifndef PackageDir
  #error PackageDir must be the complete self-contained Windows release directory.
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build-windows-installer.ps1.
#endif
#ifndef IconFile
  #error IconFile must be supplied by build-windows-installer.ps1.
#endif
#ifdef TestId
  #define ProductId "CIMCStudio.InstallerTest." + TestId
  #define ProductName "CIMC Studio Test " + TestId
  #define InstallerName "CIMC-Studio-" + AppVersion + "-Test-" + TestId + "-Setup-x64"
#else
  #define ProductId "CIMCStudio.User"
  #define ProductName "CIMC Studio"
  #define InstallerName "CIMC-Studio-" + AppVersion + "-Setup-x64"
#endif

[Setup]
AppId={#ProductId}
AppName={#ProductName}
AppVersion={#AppVersion}
AppPublisher=CIMC Studio
AppPublisherURL=https://github.com/Epiphany-Lucky/cimc-simulator
DefaultDirName={localappdata}\Programs\{#ProductName}
DefaultGroupName={#ProductName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SourceDir={#PackageDir}
OutputDir={#OutputDir}
OutputBaseFilename={#InstallerName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\CIMC-Studio.exe
UninstallDisplayName={#ProductName}
WizardStyle=modern
WizardSizePercent=110
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
Uninstallable=yes
ChangesAssociations=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#ProductName}"; Filename: "{app}\CIMC-Studio.exe"; WorkingDir: "{app}"
Name: "{group}\{#ProductName} - Web"; Filename: "{app}\CIMC-Studio.exe"; Parameters: "--web"; WorkingDir: "{app}"
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\CIMC-Studio.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\CIMC-Studio.exe"; Description: "{cm:LaunchProgram,{#ProductName}}"; Flags: nowait postinstall skipifsilent

; Deliberately no [UninstallDelete] wildcard: never remove user-created files/data.
