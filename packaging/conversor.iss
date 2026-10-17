; Inno Setup script for Conversor. Built by scripts/build_installer.py, which passes:
;   /DAppVersion=<x.y.z>  /DSourceDir=<PyInstaller output folder>  /DVariant=cpu|nvidia
; Both variants share one AppId, so either one installs over the other.

#ifndef AppVersion
  #error Pass /DAppVersion=<version>
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=<folder with Conversor.exe>
#endif
#ifndef Variant
  #define Variant "cpu"
#endif

#if Variant == "nvidia"
  #define Suffix "-setup-nvidia"
  #define Excluded ""
#else
  #define Suffix "-setup"
  ; Without these the AI tools run on the CPU (ops/ai.py checks for them).
  #define Excluded "\_internal\nvidia,\_internal\onnxruntime\capi\onnxruntime_providers_cuda.dll"
#endif

[Setup]
AppId={{A74B9201-A0A1-4E8F-AF3A-B5B39E606817}
AppName=Conversor
AppVersion={#AppVersion}
AppVerName=Conversor {#AppVersion}
AppPublisher=Conversor
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Conversor
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=Conversor-{#AppVersion}{#Suffix}
SetupIconFile=..\src\conversor\qml\icon.ico
UninstallDisplayIcon={app}\Conversor.exe
UninstallDisplayName=Conversor
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "sendto"; Description: "Add Conversor to Explorer's ""Send to"" menu"

[InstallDelete]
; Start from a clean program folder, so files from an older version or from the other
; variant (the NVIDIA libraries) never linger.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\ffmpeg"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "{#Excluded}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Conversor"; Filename: "{app}\Conversor.exe"; Comment: "Convert files locally"; AppUserModelID: "Conversor.App"
Name: "{userdesktop}\Conversor"; Filename: "{app}\Conversor.exe"; Comment: "Convert files locally"; AppUserModelID: "Conversor.App"; Tasks: desktopicon
Name: "{usersendto}\Conversor"; Filename: "{app}\Conversor.exe"; Comment: "Convert files locally"; AppUserModelID: "Conversor.App"; Tasks: sendto

[Run]
Filename: "{app}\Conversor.exe"; Description: "Open Conversor"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if SuppressibleMsgBox('Also delete Conversor''s settings, cache and downloaded AI models?' + #13#10#13#10 +
       'Your converted files are not touched either way.',
       mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
  begin
    DelTree(ExpandConstant('{userappdata}\Conversor'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\Conversor'), True, True, True);
  end;
end;
