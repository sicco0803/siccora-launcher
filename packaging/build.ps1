# Baut das eigenstaendige Paket: dist\SiccoraLauncher\SiccoraLauncher.exe
# Aufruf:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root "spike\.venv\Scripts\python.exe"

# Version aus main.py lesen -> in die exe-Eigenschaften schreiben
$version = (Select-String -Path (Join-Path $root "app\main.py") -Pattern 'APP_VERSION = "([\d.]+)"').Matches[0].Groups[1].Value
$parts = ($version.Split(".") + @("0", "0", "0"))[0..3] -join ", "
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts)),
  kids=[StringFileInfo([StringTable('040704B0', [
    StringStruct('CompanyName', 'Siccora Studio'),
    StringStruct('FileDescription', 'Siccora Launcher'),
    StringStruct('FileVersion', '$version'),
    StringStruct('ProductName', 'Siccora Launcher'),
    StringStruct('ProductVersion', '$version'),
    StringStruct('LegalCopyright', 'Siccora Studio - GPL-3.0')])]),
    VarFileInfo([VarStruct('Translation', [1031, 1200])])]
)
"@ | Set-Content (Join-Path $PSScriptRoot "version_info.txt") -Encoding utf8

# Bauumgebung muss exakt den festgeschriebenen Paketversionen entsprechen (requirements.txt) -
# so landet nie unbemerkt eine andere (evtl. untergeschobene) Paketversion im Launcher
$pinned = Select-String -Path (Join-Path $PSScriptRoot "requirements.txt") -Pattern '^([A-Za-z0-9_.-]+==\S+)' |
    ForEach-Object { $_.Matches[0].Groups[1].Value.ToLower() -replace '_', '-' } | Sort-Object
$actual = & $py -m pip freeze --all --exclude pip | ForEach-Object { $_.ToLower() -replace '_', '-' } | Sort-Object
$diff = Compare-Object $pinned $actual
if ($diff) {
    $diff | ForEach-Object { Write-Host ("  {0} {1}" -f $(if ($_.SideIndicator -eq '<=') { 'erwartet:' } else { 'installiert:' }), $_.InputObject) }
    throw "Bauumgebung weicht von packaging\requirements.txt ab"
}

Write-Host "Baue Siccora Launcher $version ..."
& $py -m PyInstaller (Join-Path $PSScriptRoot "siccora.spec") --noconfirm --clean `
    --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller ist fehlgeschlagen" }

$out = Join-Path $root "dist\SiccoraLauncher"

# Code-Signatur (Certum Open Source, SimplySign). Nur aktiv, wenn der Fingerabdruck des
# Zertifikats gesetzt ist:  $env:SICCORA_SIGN_THUMBPRINT = "<SHA1 aus SimplySign Desktop>"
# Jede Signatur muss in der SimplySign-App am Handy bestaetigt sein (Sitzung aktiv).
function Find-SignTool {
    $found = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $found) { throw "signtool.exe nicht gefunden (Windows SDK: winget install Microsoft.WindowsSDK.10.0.26100)" }
    return $found
}
function Sign-File($file) {
    if (-not $env:SICCORA_SIGN_THUMBPRINT) { return }
    $signtool = Find-SignTool
    & $signtool.FullName sign /sha1 $env:SICCORA_SIGN_THUMBPRINT /fd sha256 /tr "http://time.certum.pl" /td sha256 `
        /d "Siccora Launcher" $file
    if ($LASTEXITCODE -ne 0) { throw "Signieren fehlgeschlagen: $file" }
    Write-Host "Signiert: $file"
}
if ($env:SICCORA_SIGN_THUMBPRINT) { Sign-File (Join-Path $out "SiccoraLauncher.exe") }
else { Write-Warning "Ohne Code-Signatur gebaut (SICCORA_SIGN_THUMBPRINT nicht gesetzt)" }

$size = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Fertig: {0}\SiccoraLauncher.exe ({1:N0} MB)" -f $out, $size)

# Lizenz (GPL-3.0) gehoert zu jeder Weitergabe dazu
Copy-Item (Join-Path $root "LICENSE") (Join-Path $out "LICENSE.txt")

# Portables ZIP (entpacken und starten)
$zip = Join-Path $root "dist\SiccoraLauncher-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $out -DestinationPath $zip
Write-Host "Fertig: $zip"

# Installer (Inno Setup 6, pro Benutzer installiert)
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup 6 nicht gefunden - Installer wird nicht gebaut (winget install JRSoftware.InnoSetup)"
} else {
    # Microsofts WebView2-Installer (fuer PCs ohne WebView2) - nicht im Git, bei Bedarf laden und pruefen
    $wv2 = Join-Path $PSScriptRoot "redist\MicrosoftEdgeWebview2Setup.exe"
    if (-not (Test-Path $wv2)) {
        New-Item -ItemType Directory -Force (Split-Path $wv2) | Out-Null
        Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $wv2 -UseBasicParsing
    }
    $sig = Get-AuthenticodeSignature $wv2
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notlike "CN=Microsoft Corporation,*") {
        Remove-Item $wv2
        throw "WebView2-Installer ist nicht gueltig von Microsoft signiert"
    }
    $signArgs = @()
    if ($env:SICCORA_SIGN_THUMBPRINT) {
        $tool = (Find-SignTool).FullName
        $signArgs = @("/DUseSigning", "/Ssiccora=`$q$tool`$q sign /sha1 $env:SICCORA_SIGN_THUMBPRINT /fd sha256 /tr http://time.certum.pl /td sha256 /d `$qSiccora Launcher`$q `$f")
    }
    & $iscc /Q "/DAppVersion=$version" @signArgs (Join-Path $PSScriptRoot "installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup ist fehlgeschlagen" }
    $setup = Join-Path $root "dist\SiccoraLauncher-$version-Setup.exe"
    if ($env:SICCORA_SIGN_THUMBPRINT -and (Get-AuthenticodeSignature $setup).Status -ne "Valid") { throw "Setup ist nicht gueltig signiert" }
    Write-Host "Fertig: $setup"
}
