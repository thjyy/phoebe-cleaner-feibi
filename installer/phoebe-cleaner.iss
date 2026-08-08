#ifndef AppVersion
  #define AppVersion "0.4.1"
#endif

#ifndef SourceDir
  #error SourceDir must point to the packaged PhoebeCleanerQt directory.
#endif

#ifndef OutputDir
  #define OutputDir "..\release"
#endif

[Setup]
AppId={{A4A84F15-29A6-47A0-A5F4-862B21E88713}
AppName=Phoebe Cleaner / 菲比文件清理器
AppVersion={#AppVersion}
AppPublisher=thjyy
AppPublisherURL=https://github.com/thjyy/phoebe-cleaner-feibi
AppSupportURL=https://github.com/thjyy/phoebe-cleaner-feibi/issues
AppUpdatesURL=https://github.com/thjyy/phoebe-cleaner-feibi/releases
DefaultDirName={localappdata}\Programs\PhoebeCleaner\{#AppVersion}
UsePreviousAppDir=no
DefaultGroupName=Phoebe Cleaner
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=PhoebeCleaner-Setup-v{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\PhoebeCleanerQt.exe
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=thjyy
VersionInfoDescription=Phoebe Cleaner installer
VersionInfoProductName=Phoebe Cleaner
VersionInfoProductVersion={#AppVersion}

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\菲比清理设置"; Filename: "{app}\PhoebeCleanerQt.exe"; Parameters: "--settings"; WorkingDir: "{app}"; IconFilename: "{app}\PhoebeCleanerQt.exe"; Comment: "选择菲比动画的简洁、标准或戏剧化速度"

[Registry]
Root: HKCU; Subkey: "Software\Classes\CLSID\{{7B0EE0AD-A02E-4B17-B55F-389713265BF2}\InprocServer32"; ValueType: string; ValueName: ""; ValueData: "{app}\PhoebeShellExtension.dll"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\CLSID\{{7B0EE0AD-A02E-4B17-B55F-389713265BF2}\InprocServer32"; ValueType: string; ValueName: "ThreadingModel"; ValueData: "Apartment"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved"; ValueType: string; ValueName: "{{7B0EE0AD-A02E-4B17-B55F-389713265BF2}"; ValueData: "Phoebe Cleaner Explorer Command"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\*\shell\PhoebeCleaner"; ValueType: string; ValueName: ""; ValueData: "召唤菲比来清理"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\PhoebeCleaner"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\PhoebeCleanerQt.exe"
Root: HKCU; Subkey: "Software\Classes\*\shell\PhoebeCleaner"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"
Root: HKCU; Subkey: "Software\Classes\*\shell\PhoebeCleaner"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{7B0EE0AD-A02E-4B17-B55F-389713265BF2}"
Root: HKCU; Subkey: "Software\Classes\Directory\shell\PhoebeCleaner"; ValueType: string; ValueName: ""; ValueData: "召唤菲比来清理"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\PhoebeCleaner"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\PhoebeCleanerQt.exe"
Root: HKCU; Subkey: "Software\Classes\Directory\shell\PhoebeCleaner"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"
Root: HKCU; Subkey: "Software\Classes\Directory\shell\PhoebeCleaner"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{7B0EE0AD-A02E-4B17-B55F-389713265BF2}"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\PhoebeCleaner"

[Code]
procedure StopAnimationServer();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM PhoebeCleanerQt.exe /F >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopAnimationServer();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopAnimationServer();
end;
