#ifndef AppVersion
  #define AppVersion "1.0.2"
#endif

#define AppName "Research Analysis System"
#define AppExeName "ResearchAnalysis.exe"
#define AppIcon "..\assets\research_analysis.ico"
#ifndef AppDistDir
  #define AppDistDir "..\dist\ResearchAnalysis"
#endif
#ifndef AppOutputDir
  #define AppOutputDir "..\dist\installer"
#endif

[Setup]
AppId={{45e12012-4d3e-4911-b837-70c40ac85206}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=David Sunday Onah
AppPublisherURL=https://github.com/davidsundayonah/research-analysis-system
AppSupportURL=https://github.com/davidsundayonah/research-analysis-system/issues
AppUpdatesURL=https://github.com/davidsundayonah/research-analysis-system/releases
DefaultDirName={code:GetDefaultInstallDir}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
UsePreviousAppDir=yes
UsePreviousGroup=yes
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
SetupLogging=yes
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir={#AppOutputDir}
OutputBaseFilename=ResearchAnalysis_Setup
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=David Sunday Onah
VersionInfoDescription=Research Analysis System Setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile={#AppIcon}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#AppDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ResolvedLocalAppData: String;

function IsAbsoluteWindowsPath(const Value: String): Boolean;
begin
  Result := ((Length(Value) >= 3) and (Value[2] = ':') and (Value[3] = '\')) or
    ((Length(Value) >= 2) and (Copy(Value, 1, 2) = '\\'));
end;

function ResolveLocalAppData: String;
var
  Candidate: String;
  UserProfile: String;
  EnvironmentWasSet: Boolean;
begin
  Result := '';
  Candidate := Trim(GetEnv('LOCALAPPDATA'));
  EnvironmentWasSet := Candidate <> '';

  // Prefer the supported environment value. Avoid shell-folder expansion,
  // which requests shell-folder creation and can fail on valid profiles that
  // lack the legacy Explorer\Shell Folders cache.
  if IsAbsoluteWindowsPath(Candidate) and DirExists(Candidate) then begin
    Log('Resolved per-user Local AppData from the LOCALAPPDATA environment variable.');
    Result := RemoveBackslashUnlessRoot(Candidate);
    Exit;
  end;
  if EnvironmentWasSet then
    Log('LOCALAPPDATA is set but is not an existing absolute directory; checking the Windows shell folder.');

  // Query the existing known folder without requesting shell-folder creation.
  Candidate := GetShellFolderByCSIDL($001C, False);
  if IsAbsoluteWindowsPath(Candidate) and DirExists(Candidate) then begin
    Log('Resolved per-user Local AppData through the Windows shell folder API.');
    Result := RemoveBackslashUnlessRoot(Candidate);
    Exit;
  end;

  // Only use the standard profile location when LOCALAPPDATA is absent. If it
  // was explicitly set but invalid, fail rather than silently write elsewhere.
  if EnvironmentWasSet then begin
    Log('Could not resolve the explicitly configured LOCALAPPDATA directory.');
    Exit;
  end;

  UserProfile := Trim(GetEnv('USERPROFILE'));
  if not IsAbsoluteWindowsPath(UserProfile) or not DirExists(UserProfile) then begin
    Log('LOCALAPPDATA and USERPROFILE are unavailable or invalid.');
    Exit;
  end;

  Candidate := AddBackslash(UserProfile) + 'AppData\Local';
  if not DirExists(Candidate) and not ForceDirectories(Candidate) then begin
    Log('Could not create the standard per-user Local AppData directory under USERPROFILE.');
    Exit;
  end;
  if DirExists(Candidate) then begin
    Log('Resolved per-user Local AppData from USERPROFILE after the environment and shell folder were unavailable.');
    Result := RemoveBackslashUnlessRoot(Candidate);
  end;
end;

function GetDefaultInstallDir(Param: String): String;
begin
  if IsAdminInstallMode then
    Result := ExpandConstant('{commonpf64}\Research Analysis System')
  else begin
    if ResolvedLocalAppData = '' then
      ResolvedLocalAppData := ResolveLocalAppData;
    if ResolvedLocalAppData = '' then
      Result := ''
    else
      Result := AddBackslash(ResolvedLocalAppData) + 'Programs\Research Analysis System';
  end;
end;

function VCRuntimeInstalled: Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64') or
    RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64');
end;

function InitializeSetup(): Boolean;
var
  Choice: Integer;
  ErrorCode: Integer;
begin
  Result := True;
  if not IsAdminInstallMode then begin
    ResolvedLocalAppData := ResolveLocalAppData;
    if ResolvedLocalAppData = '' then begin
      Log('Setup stopped because no usable per-user Local AppData directory could be resolved.');
      MsgBox('Windows did not provide a usable Local AppData directory for this user. Check the LOCALAPPDATA and USERPROFILE environment variables or sign in with a fully initialized Windows profile, then run Setup again.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
  if not VCRuntimeInstalled then begin
    Choice := MsgBox('The Microsoft Visual C++ 2015-2022 x64 Redistributable was not detected. It may be required by this application. Open the official Microsoft download page before continuing?', mbConfirmation, MB_YESNO);
    if Choice = IDYES then begin
      ShellExec('open', 'https://aka.ms/vs/17/release/vc_redist.x64.exe', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
    end;
  end;
end;
