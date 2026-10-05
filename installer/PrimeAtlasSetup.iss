; PrimeAtlasSetup.iss -- Inno Setup 6 script for PrimeAtlasSetup.exe, an OFFLINE installer:
; the pinned CPython and MinGit runtimes are bundled inside the exe (prepared by
; build_installer.py into installer\vendor\), only the app itself comes from GitHub.
;
; Why offline: an installer that downloads runtimes itself and runs git/pip through a hidden
; cmd.exe matches a Windows Defender ML heuristic (Trojan:Win32/Bearfoos.B!ml). There is no
; download code here and no cmd.exe: at install time only the (signed) git.exe and
; python.exe touch the network (git clone, pip install).
;
; Why a bootstrapper instead of a frozen (PyInstaller) app: PrimeAtlas runs out of its own git
; checkout (primeatlas/settings/app_update.py self-updates with git fetch), relies on
; sys.executable being a real Python (pip installs, the ring_viz renderer subprocess,
; app_restart.py), and runs plain .py files inside WSL -- a frozen exe breaks all three.
;
; Layout under the chosen directory (default %LOCALAPPDATA%\PrimeAtlas, no admin rights):
;   {app}\python   full CPython 3.13 ZIP from python.org (the package the Python install
;                  manager itself uses: includes tkinter and pip, touches no registry, never
;                  conflicts with a Python the user already has). NOT 3.14: moderngl and
;                  glcontext ship no 3.14 wheels, so pip would try (and fail) to compile them.
;   {app}\git      portable MinGit, NOT on PATH -- app_update.git_executable() finds it here.
;   {app}\app      git clone of the repo; generated data defaults to
;                  {app}\app\CONSTELLATION_PORTAL (see AppSettings.default_storage_path).
; The WSL backend is NOT handled here: the app's own first-run wizard (env_setup_wizard.py)
; takes over on first launch, exactly as for a hand-made clone.
;
; Build:  python installer\build_installer.py   ->  installer\Output\PrimeAtlasSetup.exe
; (downloads + SHA-256-verifies the ZIPs pinned below, extracts them to installer\vendor\,
; runs ISCC). The #define pins below are the single source of truth for that script.
; Contract pinned by unitTests/test_installer_script.py.

#define AppName "PrimeAtlas"
; AppVersion comes from primeatlas\core\version.py (APP_VERSION), passed in by
; build_installer.py as /DAppVersion=... -- one version number for the app and the installer.
#ifndef AppVersion
  #error Build with installer\build_installer.py: it passes /DAppVersion from primeatlas\core\version.py
#endif
#define RepoUrl "https://github.com/Flaman55/primeAtlas.git"
#define RepoBranch "main"
#define RepoWebUrl "https://github.com/Flaman55/primeAtlas"

#define PythonVersion "3.13.15"
#define PythonSha256 "6479223746cdfb79d25865110d6f524ac98de081324e119af1dc3ae36bddc7a5"
#define PythonUrl "https://www.python.org/ftp/python/" + PythonVersion + "/python-" + PythonVersion + "-amd64.zip"

#define MinGitVersion "2.56.0"
#define MinGitTag "v2.56.0.windows.1"
#define MinGitSha256 "064b440ff870ed5198527e8f3a92cdf5bd2fd0fedf5e718af95e3fdaddeff718"
#define MinGitUrl "https://github.com/git-for-windows/git/releases/download/" + MinGitTag + "/MinGit-" + MinGitVersion + "-64-bit.zip"

[Setup]
AppId={{479646B0-B82F-4702-B105-15627F083B59}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL={#RepoWebUrl}
DefaultDirName={localappdata}\PrimeAtlas
DisableDirPage=no
DirExistsWarning=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=PrimeAtlasSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern dynamic windows11
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\primeatlas.ico
SetupIconFile=..\primeatlas\core\assets\primeatlas.ico
SetupLogging=yes

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
polish.TaskGroup=Skróty:
polish.TaskDesktop=Utwórz skrót na pulpicie
polish.TaskStartMenu=Utwórz skrót w menu Start
polish.LaunchApp=Uruchom PrimeAtlas
polish.OpenReadme=Otwórz opis programu (README na GitHubie)
polish.StatusCloning=Pobieranie PrimeAtlas z GitHuba...
polish.StatusUpdating=Aktualizowanie PrimeAtlas z GitHuba...
polish.StatusPip=Instalowanie pakietów Pythona (numpy, moderngl, glfw, Pillow)...
polish.CloneFailed=Nie udało się pobrać PrimeAtlas z GitHuba. Sprawdź połączenie z internetem i uruchom instalator ponownie.%n%nSzczegóły w pliku:%n%1
polish.PullFailed=Nie udało się zaktualizować istniejącej kopii PrimeAtlas (np. ma lokalne zmiany) -- pozostawiono ją bez zmian.%n%nSzczegóły w pliku:%n%1
polish.PipFailed=Nie udało się zainstalować pakietów Pythona. PrimeAtlas zaproponuje ich instalację przy pierwszym uruchomieniu.%n%nSzczegóły w pliku:%n%1
polish.DirNotEmpty=Folder%n%1%nzawiera już inne pliki. Wybierz pusty folder (lub nowy, np. %1\PrimeAtlas) albo folder wcześniejszej instalacji PrimeAtlas.
polish.AppDirNotRepo=Folder%n%1%njuż istnieje i nie jest instalacją PrimeAtlas. Wybierz inny katalog instalacji.
polish.UninstallAskData=Usunąć także wygenerowane dane PrimeAtlas?%n%n%1%n%nMogą to być wyniki wielu godzin obliczeń. Wybierz „Nie”, aby je zachować.
english.TaskGroup=Shortcuts:
english.TaskDesktop=Create a desktop shortcut
english.TaskStartMenu=Create a Start menu shortcut
english.LaunchApp=Launch PrimeAtlas
english.OpenReadme=Open the program description (README on GitHub)
english.StatusCloning=Downloading PrimeAtlas from GitHub...
english.StatusUpdating=Updating PrimeAtlas from GitHub...
english.StatusPip=Installing Python packages (numpy, moderngl, glfw, Pillow)...
english.CloneFailed=Could not download PrimeAtlas from GitHub. Check your internet connection and run the installer again.%n%nDetails in:%n%1
english.PullFailed=Could not update the existing PrimeAtlas copy (e.g. it has local changes) -- it was left unchanged.%n%nDetails in:%n%1
english.PipFailed=Could not install the Python packages. PrimeAtlas will offer to install them on first launch.%n%nDetails in:%n%1
english.DirNotEmpty=The folder%n%1%nalready contains other files. Please choose an empty (or new) folder, e.g. %1\PrimeAtlas, or the folder of an earlier PrimeAtlas installation.
english.AppDirNotRepo=The folder%n%1%nalready exists and is not a PrimeAtlas installation. Please choose another install directory.
english.UninstallAskData=Also delete the generated PrimeAtlas data?%n%n%1%n%nThis may be the result of many hours of computation. Choose "No" to keep it.

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:TaskGroup}"
Name: "startmenuicon"; Description: "{cm:TaskStartMenu}"; GroupDescription: "{cm:TaskGroup}"

[Files]
; Extracted, SHA-256-verified runtimes prepared by build_installer.py.
Source: "vendor\python\*"; DestDir: "{app}\python"; Excludes: ".extracted-from-sha256"; Flags: recursesubdirs createallsubdirs ignoreversion
; The installer's own copy of the icon: [Icons] runs BEFORE ssPostInstall clones the repo, so
; shortcuts pointing into {app}\app would get a blank icon on a fresh install.
Source: "..\primeatlas\core\assets\primeatlas.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "vendor\git\*"; DestDir: "{app}\git"; Excludes: ".extracted-from-sha256"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\prime_atlas_v2.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\primeatlas.ico"; AppUserModelID: "Flaman55.PrimeAtlas"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\prime_atlas_v2.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\primeatlas.ico"; AppUserModelID: "Flaman55.PrimeAtlas"; Tasks: startmenuicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\prime_atlas_v2.py"""; WorkingDir: "{app}\app"; Description: "{cm:LaunchApp}"; Flags: postinstall nowait skipifsilent; Check: AppInstalled
; The README as a GitHub page, not the local .md: a fresh Windows has no app for .md files.
Filename: "{#RepoWebUrl}#readme"; Description: "{cm:OpenReadme}"; Flags: postinstall shellexec nowait skipifsilent

[UninstallDelete]
; pip-installed packages and anything else not logged by [Files]. {app}\app is handled in
; code, because it may hold the user's generated data.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\git"
Type: files; Name: "{app}\install.log"

[Code]
const
  // Written at ssInstall, before anything else: identifies a folder as ours (also after an
  // interrupted install, and after an uninstall that kept the user's data).
  MarkerName = 'primeatlas-install.id';
  DataDirName = 'CONSTELLATION_PORTAL';

var
  AppReady: Boolean;

function AppInstalled: Boolean;
begin
  Result := AppReady;
end;

procedure InitializeWizard;
begin
  // The glyph-to-label gap does not grow with DPI, so above 100% display scaling the
  // checkbox labels overlap the right edge of the DPI-scaled check square. Widen it by what
  // the ~13px square grows with DPI, plus 2px: +2 at 100%, +6 at 125%, +10 at 150%.
  WizardForm.TasksList.Offset := WizardForm.TasksList.Offset + ScaleX(15) - 13;
  WizardForm.RunList.Offset := WizardForm.RunList.Offset + ScaleX(15) - 13;
end;

function DirIsEmpty(const Dir: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := True;
  if FindFirst(Dir + '\*', FindRec) then
  try
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') then begin
        Result := False;
        Exit;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

function IsOurInstall(const Dir: String): Boolean;
begin
  // The unins000.exe + app\.git fallback recognizes builds made before the marker existed.
  Result := FileExists(AddBackslash(Dir) + MarkerName) or
            (FileExists(AddBackslash(Dir) + 'unins000.exe') and DirExists(AddBackslash(Dir) + 'app\.git'));
end;

// True if Dir holds nothing but a CONSTELLATION_PORTAL folder (what an uninstall that kept
// the data leaves behind in {app}\app).
function OnlyDataInside(const Dir: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := True;
  if FindFirst(Dir + '\*', FindRec) then
  try
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') and (CompareText(FindRec.Name, DataDirName) <> 0) then begin
        Result := False;
        Exit;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  AppDir: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    // Only a new/empty folder or an earlier PrimeAtlas install: the uninstaller deletes
    // {app}\python and {app}\git wholesale, which must never hit a user's own folders.
    if DirExists(WizardDirValue) and not DirIsEmpty(WizardDirValue) and not IsOurInstall(WizardDirValue) then begin
      SuppressibleMsgBox(FmtMessage(CustomMessage('DirNotEmpty'), [RemoveBackslashUnlessRoot(WizardDirValue)]), mbError, MB_OK, IDOK);
      Result := False;
      Exit;
    end;
    // Never clone over (or pull in) an app folder that is not ours.
    AppDir := AddBackslash(WizardDirValue) + 'app';
    if DirExists(AppDir) and not DirExists(AppDir + '\.git') and not OnlyDataInside(AppDir) then begin
      SuppressibleMsgBox(FmtMessage(CustomMessage('AppDirNotRepo'), [AppDir]), mbError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

procedure AppendLines(const LogFile: String; const Lines: TArrayOfString);
begin
  SaveStringsToUTF8FileWithoutBOM(LogFile, Lines, True);
end;

procedure AppendLine(const LogFile, Line: String);
var
  Lines: TArrayOfString;
begin
  SetArrayLength(Lines, 1);
  Lines[0] := Line;
  AppendLines(LogFile, Lines);
end;

// Runs Exe directly (no command-shell wrapper), appends its stdout/stderr to
// {app}\install.log (UTF-8, so non-ASCII install paths stay readable) and returns its exit
// code (-1 if it could not be started at all).
function RunLogged(const Exe, Params, Status: String): Integer;
var
  LogFile: String;
  ResultCode: Integer;
  Output: TExecOutput;
begin
  WizardForm.StatusLabel.Caption := Status;
  WizardForm.FilenameLabel.Caption := '';
  LogFile := ExpandConstant('{app}\install.log');
  AppendLine(LogFile, '');
  AppendLine(LogFile, '> "' + Exe + '" ' + Params);
  if not ExecAndCaptureOutput(Exe, Params, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode, Output) then
    ResultCode := -1;
  AppendLines(LogFile, Output.StdOut);
  AppendLines(LogFile, Output.StdErr);
  AppendLine(LogFile, '[exit code ' + IntToStr(ResultCode) + ']');
  Log(Format('%s %s -> %d', [Exe, Params, ResultCode]));
  Result := ResultCode;
end;

// git clone refuses a non-empty target, but a reinstall after an uninstall that kept the
// data finds {app}\app holding just CONSTELLATION_PORTAL: park it next to {app}\app, clone,
// then move it back (also if the clone fails, so the data is never left stranded).
function CloneKeepingData(const Git, AppDir: String): Boolean;
var
  DataDir, Parked: String;
begin
  DataDir := AppDir + '\' + DataDirName;
  Parked := ExpandConstant('{app}\') + DataDirName + '.parked';
  if DirExists(DataDir) and not DirExists(Parked) then
    RenameFile(DataDir, Parked);
  if DirExists(AppDir) and DirIsEmpty(AppDir) then
    RemoveDir(AppDir);
  Result := RunLogged(Git, 'clone --branch {#RepoBranch} "{#RepoUrl}" "' + AppDir + '"', CustomMessage('StatusCloning')) = 0;
  if DirExists(Parked) and not DirExists(DataDir) then begin
    ForceDirectories(AppDir);
    RenameFile(Parked, DataDir);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, Git, Python, LogFile: String;
begin
  if CurStep = ssInstall then begin
    ForceDirectories(ExpandConstant('{app}'));
    SaveStringToFile(ExpandConstant('{app}\') + MarkerName, '{#AppName}' + #13#10, False);
    Exit;
  end;
  if CurStep <> ssPostInstall then
    Exit;
  AppDir := ExpandConstant('{app}\app');
  Git := ExpandConstant('{app}\git\cmd\git.exe');
  Python := ExpandConstant('{app}\python\python.exe');
  LogFile := ExpandConstant('{app}\install.log');
  WizardForm.ProgressGauge.Style := npbstMarquee;
  try
    if DirExists(AppDir + '\.git') then begin
      // Reinstall over an existing clone: fast-forward only, never overwrite local changes.
      if RunLogged(Git, '-C "' + AppDir + '" pull --ff-only', CustomMessage('StatusUpdating')) <> 0 then
        SuppressibleMsgBox(FmtMessage(CustomMessage('PullFailed'), [LogFile]), mbInformation, MB_OK, IDOK);
    end else begin
      if not CloneKeepingData(Git, AppDir) then begin
        SuppressibleMsgBox(FmtMessage(CustomMessage('CloneFailed'), [LogFile]), mbCriticalError, MB_OK, IDOK);
        Exit;
      end;
    end;
    AppReady := True;
    // Binary wheels only: user machines have no compiler, so a missing wheel should fail
    // fast with a clear message instead of a long, doomed source build. A failure here is
    // not fatal -- startup_dependency_check.py offers the same install on first launch.
    if RunLogged(Python, '-m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: -r "' + AppDir + '\requirements.txt"',
                 CustomMessage('StatusPip')) <> 0 then
      SuppressibleMsgBox(FmtMessage(CustomMessage('PipFailed'), [LogFile]), mbInformation, MB_OK, IDOK);
  finally
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
end;

// Deletes everything inside AppDir except its CONSTELLATION_PORTAL data folder.
procedure DeleteAppKeepingData(const AppDir: String);
var
  FindRec: TFindRec;
  Path: String;
begin
  if FindFirst(AppDir + '\*', FindRec) then
  try
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') and (CompareText(FindRec.Name, 'CONSTELLATION_PORTAL') <> 0) then begin
        Path := AppDir + '\' + FindRec.Name;
        if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          DelTree(Path, True, True, True)
        else
          DeleteFile(Path);
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDir, DataDir: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then begin
    // Kept data keeps the marker, so reinstalling into this folder stays allowed.
    if not DirExists(ExpandConstant('{app}\app')) then begin
      DeleteFile(ExpandConstant('{app}\') + MarkerName);
      RemoveDir(ExpandConstant('{app}'));
    end;
    Exit;
  end;
  if CurUninstallStep <> usUninstall then
    Exit;
  AppDir := ExpandConstant('{app}\app');
  if not DirExists(AppDir) then
    Exit;
  // git marks its object files read-only, which DeleteFile/DelTree would skip.
  Exec(ExpandConstant('{sys}\attrib.exe'), '-R "' + AppDir + '\*" /S /D', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  DataDir := AppDir + '\' + DataDirName;
  if DirExists(DataDir) and not DirIsEmpty(DataDir) then begin
    // Default (and silent-mode) answer is No: keep the data.
    if SuppressibleMsgBox(FmtMessage(CustomMessage('UninstallAskData'), [DataDir]),
                          mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      DelTree(AppDir, True, True, True)
    else
      DeleteAppKeepingData(AppDir);
  end else
    DelTree(AppDir, True, True, True);
end;
