; mangatl's installer (MT-024 C-7, AC-8). Compiled by the `installer` gate:
;   ISCC packaging/installer.iss  ->  dist/installer/mangatl-setup.exe
; It packs the PyInstaller tree `build` produced, as it is. Per-user and
; without elevation (PrivilegesRequired=lowest, a {localappdata} target), so
; installing is one double-click with no UAC prompt. 64-bit only.
; AppVersion re-spells pyproject.toml's [project].version; a test pins equality.
; Compression is lzma2/fast, not solid: ~2.5 GB of DLLs and weights.
; Inno Setup has no inline comments - a ";" after a value is part of it.

[Setup]
AppName=mangatl
AppVersion=0.1.0
DefaultDirName={localappdata}\Programs\mangatl
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=mangatl-setup
Compression=lzma2/fast
SolidCompression=no
DisableProgramGroupPage=yes

[Files]
Source: "..\dist\mangatl\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\mangatl"; Filename: "{app}\mangatl.exe"
