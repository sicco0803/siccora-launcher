; Installer fuer den Siccora Launcher (Inno Setup 6).
; Wird von build.ps1 aufgerufen, die Version kommt aus app\main.py:
;   ISCC.exe /DAppVersion=1.0.0 packaging\installer.iss
;
; - Installiert pro Benutzer nach %LOCALAPPDATA%\Programs\Siccora Launcher,
;   braucht also KEINE Administratorrechte.
; - Updates: einfach die neuere Setup-exe ausfuehren. Die feste AppId sorgt dafuer,
;   dass sie ueber die alte Version installiert. Anmeldung, Einstellungen und
;   Bibliothek liegen ausserhalb des Programmordners und bleiben erhalten.
; - Deinstallieren entfernt nur das Programm, nie installierte Spiele/Engines.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Siccora Launcher"
#define AppExe "SiccoraLauncher.exe"

[Setup]
; NIE aendern - daran erkennt Windows, dass ein Update dieselbe App ist.
AppId={{A946B0A1-D881-42FD-BCA3-5561A5B27731}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Siccora Studio
AppCopyright=Siccora Studio - GPL-3.0
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 1809 oder neuer (Grundlage fuer WebView2 und .NET Framework 4.7.2)
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=SiccoraLauncher-{#AppVersion}-Setup
SetupIconFile=siccora.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Laufenden Launcher vor dem Update schliessen (sonst sind Dateien gesperrt)
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=auto

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[CustomMessages]
de.WebView2Installing=Installiere Microsoft Edge WebView2 (wird für die Oberfläche benötigt) ...
en.WebView2Installing=Installing Microsoft Edge WebView2 (required for the interface) ...
de.WebView2Failed=Microsoft Edge WebView2 konnte nicht installiert werden (evtl. keine Internetverbindung).%n%nDer Launcher braucht es für seine Oberfläche. Bitte später von Microsoft installieren:%nhttps://go.microsoft.com/fwlink/p/?LinkId=2124703
en.WebView2Failed=Microsoft Edge WebView2 could not be installed (maybe no internet connection).%n%nThe launcher needs it for its interface. Please install it from Microsoft later:%nhttps://go.microsoft.com/fwlink/p/?LinkId=2124703
de.DotNetMissing=Für den Siccora Launcher wird .NET Framework 4.7.2 oder neuer benötigt.%n%nBitte Windows über Windows Update aktualisieren und das Setup danach erneut starten.
en.DotNetMissing=Siccora Launcher requires .NET Framework 4.7.2 or newer.%n%nPlease update Windows via Windows Update and run setup again.

[Files]
Source: "..\dist\SiccoraLauncher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Microsofts offizieller WebView2-Installer (signiert, ~2 MB) - nur genutzt, wenn WebView2 fehlt
Source: "redist\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Registry]
; "Mit Windows starten" legt der Launcher selbst an - beim Deinstallieren wieder entfernen
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "SiccoraLauncher"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"; ValueType: none; ValueName: "SiccoraLauncher"; Flags: uninsdeletevalue

[InstallDelete]
; Bei einem Update alte Programmdateien vorher entfernen, damit keine Reste
; einer frueheren Version mitgeladen werden.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Update aus dem Launcher (still gestartet): danach automatisch wieder oeffnen
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[Code]
const
  WebView2Guid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

{ WebView2 Runtime vorhanden? Microsoft nennt diese drei Stellen (Rechner 64/32 Bit, Benutzer). }
function WebView2Version(Root: Integer; Key: String): String;
begin
  if not RegQueryStringValue(Root, Key + WebView2Guid, 'pv', Result) then
    Result := '';
end;

function WebView2Installed: Boolean;
var
  V: String;
begin
  V := WebView2Version(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\');
  if (V = '') or (V = '0.0.0.0') then
    V := WebView2Version(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\');
  if (V = '') or (V = '0.0.0.0') then
    V := WebView2Version(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\');
  Result := (V <> '') and (V <> '0.0.0.0');
end;

{ .NET Framework 4.7.2+ (fuer die Verbindung zu den Windows-Fenstern) - ab Windows 10 1803 eingebaut }
function DotNetOk: Boolean;
var
  Release: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release)
            and (Release >= 461808);
end;

function InitializeSetup: Boolean;
begin
  Result := DotNetOk;
  if not Result then
    SuppressibleMsgBox(CustomMessage('DotNetMissing'), mbCriticalError, MB_OK, IDOK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  if WebView2Installed then
    Exit;
  WizardForm.PreparingLabel.Caption := CustomMessage('WebView2Installing');
  WizardForm.PreparingLabel.Visible := True;
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE,
       ewWaitUntilTerminated, Code);
  if not WebView2Installed then
    SuppressibleMsgBox(CustomMessage('WebView2Failed'), mbError, MB_OK, IDOK);  { Installation laeuft trotzdem weiter }
end;
