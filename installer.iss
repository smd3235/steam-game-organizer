; Steam Game Organizer Installer Script
; Compiled with ISCC.exe (Inno Setup Compiler)
; Build: steam-game-organizer.exe --build-installer

[Setup]
AppName=Steam Game Organizer
AppVersion=1.0
AppPublisher=Steam Game Organizer
DefaultDirName={pf}\Steam Game Organizer
DefaultGroupName=Steam Game Organizer
AllowNoIcons=yes
LicenseFile=
OutputDir=output
OutputBaseFilename=Steam Game Organizer Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The main application executable
Source: "target\release\steam-game-organizer.exe"; DestDir: "{app}"; Flags: ignoreversion

; 7-Zip runtime for archive extraction
Source: "runtime\7z.exe"; DestDir: "{app}\runtime"; Flags: ignoreversion

; Assets
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\Steam Game Organizer"; Filename: "{app}\steam-game-organizer.exe"
Name: "{desktop}\Steam Game Organizer"; Filename: "{app}\steam-game-organizer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\steam-game-organizer.exe"; Description: "{cm:LaunchProgram,Steam Game Organizer}"; Flags: nowait postinstall skipifsilent
