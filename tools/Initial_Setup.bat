@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "ONECLICKLOG_CANOE19_HELPER=%~f0"
set "ONECLICKLOG_CANOE19_MODE=%~1"
set "ONECLICKLOG_CANOE19_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "ONECLICKLOG_CANOE19_POWERSHELL=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%ONECLICKLOG_CANOE19_POWERSHELL%" -NoLogo -NoProfile -Command "$text=[IO.File]::ReadAllText($env:ONECLICKLOG_CANOE19_HELPER,[Text.Encoding]::UTF8); $mark='# POWERSHELL_PAYLOAD_BEGIN'; $pos=$text.LastIndexOf($mark); if($pos -lt 0){exit 90}; & ([scriptblock]::Create($text.Substring($pos+$mark.Length)))"
set "ONECLICKLOG_CANOE19_RESULT=%errorlevel%"
echo.
if /i "%ONECLICKLOG_CANOE19_MODE%"=="--check" goto finish
pause
:finish
exit /b %ONECLICKLOG_CANOE19_RESULT%
# POWERSHELL_PAYLOAD_BEGIN
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

function Get-CanoeServer {
    param([Microsoft.Win32.RegistryView]$View)
    $base = $null; $class = $null; $server = $null
    try {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::ClassesRoot, $View)
        $class = $base.OpenSubKey('CANoe.Application\CLSID')
        if ($null -eq $class) { return '' }
        $classId = [string]$class.GetValue('')
        if ($classId -notmatch '^\{[0-9A-Fa-f-]{36}\}$') { return '' }
        $server = $base.OpenSubKey(('CLSID\{0}\LocalServer32' -f $classId))
        if ($null -eq $server) { return '' }
        $command = [string]$server.GetValue('')
        if ($command -match '^\s*"([^\"]+\.exe)"') { return $matches[1] }
        if ($command -match '^\s*(.+?\.exe)(?:\s|$)') { return $matches[1] }
        return ''
    } finally {
        if ($null -ne $server) { $server.Close() }
        if ($null -ne $class) { $class.Close() }
        if ($null -ne $base) { $base.Close() }
    }
}

function Get-CanoeVersion {
    param([string]$Path)
    return [Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
}

function Get-Canoe19Tools {
    $roots = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($programFolder in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432)) {
        if ([string]::IsNullOrWhiteSpace($programFolder) -or -not (Test-Path -LiteralPath $programFolder -PathType Container)) { continue }
        foreach ($folder in @(Get-ChildItem -LiteralPath $programFolder -Directory -Filter '*CANoe*19*' -ErrorAction SilentlyContinue)) {
            [void]$roots.Add($folder.FullName)
        }
    }
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
        $base = $null; $vector = $null
        try {
            $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, $view)
            $vector = $base.OpenSubKey('SOFTWARE\Vector\CANoe')
            if ($null -ne $vector) {
                foreach ($name in $vector.GetSubKeyNames()) {
                    $entry = $vector.OpenSubKey($name)
                    try {
                        $install = [string]$entry.GetValue('Path')
                        if ($install -and (Test-Path -LiteralPath $install -PathType Container)) { [void]$roots.Add([IO.Path]::GetFullPath($install)) }
                    } finally { if ($null -ne $entry) { $entry.Close() } }
                }
            }
        } catch { Write-Host ('Registry discovery warning: ' + $_.Exception.Message) -ForegroundColor Yellow }
        finally {
            if ($null -ne $vector) { $vector.Close() }
            if ($null -ne $base) { $base.Close() }
        }
    }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($root in $roots) {
        Write-Host ('Search: ' + $root)
        foreach ($tool in @(Get-ChildItem -LiteralPath $root -File -Filter RegisterComponents.exe -Recurse -ErrorAction SilentlyContinue)) {
            # Pair the utility with its own 64-bit CANoe executable, never a different version.
            $application = Join-Path $tool.DirectoryName 'CANoe64.exe'
            if (-not (Test-Path -LiteralPath $application -PathType Leaf)) { continue }
            $info = Get-CanoeVersion -Path $application
            if ($info.FileMajorPart -ne 19 -or -not $seen.Add($tool.FullName)) { continue }
            $signature = Get-AuthenticodeSignature -LiteralPath $tool.FullName
            $valid = $signature.Status -eq 'Valid' -and $null -ne $signature.SignerCertificate -and $signature.SignerCertificate.Subject -match 'Vector Informatik'
            [pscustomobject]@{ Tool=$tool.FullName; Application=$application; Version=$info.FileVersion; Signature=[string]$signature.Status; TrustedVector=$valid }
        }
    }
}

function Assert-ToolsClosed {
    $running = @(Get-Process -ErrorAction Stop | Where-Object { $_.ProcessName -in @('CANoe','CANoe32','CANoe64','One Click Log','One_Click_Log','AutoLog','Auto_Log') })
    if ($running.Count) {
        $description = ($running | ForEach-Object { '{0} (PID {1})' -f $_.ProcessName,$_.Id }) -join ', '
        throw ('Save your work and close One Click Log and ALL CANoe windows, then run this BAT again. Running: ' + $description)
    }
}

function Invoke-Canoe19Registration {
    param([bool]$CheckOnly)
    Write-Host 'One Click Log - Initial setup: CANoe 19 COM' -ForegroundColor Cyan
    Write-Host 'This changes the Windows CANoe automation target to version 19 when registration is run.'
    $before = Get-CanoeServer -View Registry64
    Write-Host ('Current 64-bit COM server: ' + $(if ($before) { $before } else { '(not registered)' }))
    $candidates = @(Get-Canoe19Tools)
    if (-not $candidates.Count) {
        Write-Host 'No matching RegisterComponents.exe + CANoe64.exe version 19 pair was found.' -ForegroundColor Yellow
        Write-Host 'No registration tool was run. Check the real CANoe 19 installation folder or ask your PC administrator to repair the installation.'
        return 2
    }
    for ($index = 0; $index -lt $candidates.Count; $index++) {
        $item = $candidates[$index]
        Write-Host ('[{0}] {1}' -f ($index+1),$item.Tool)
        Write-Host ('    CANoe: {0}; signature: {1}; trusted Vector: {2}' -f $item.Version,$item.Signature,$item.TrustedVector)
    }
    if ($CheckOnly) {
        Write-Host 'CHECK ONLY: no tool was executed and no COM registration was changed.' -ForegroundColor Green
        if (@($candidates | Where-Object { $_.TrustedVector }).Count) { return 0 }
        return 3
    }
    Assert-ToolsClosed
    $selected = $candidates[0]
    if ($candidates.Count -gt 1) {
        $answer = Read-Host 'More than one version 19 installation was found. Enter its number, or press Enter to cancel'
        $number = 0
        if (-not [int]::TryParse($answer, [ref]$number) -or $number -lt 1 -or $number -gt $candidates.Count) { Write-Host 'Cancelled. No tool was run.'; return 4 }
        $selected = $candidates[$number-1]
    }
    if (-not $selected.TrustedVector) { throw 'The chosen tool does not have a valid Vector signature. It was NOT executed.' }
    # Recheck after user input, immediately before asking Windows for elevation.
    Assert-ToolsClosed
    $selectedVersion = Get-CanoeVersion -Path $selected.Application
    if ($selectedVersion.FileMajorPart -ne 19) { throw 'The chosen CANoe executable is no longer version 19. No tool was run.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $selected.Tool
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch 'Vector Informatik') { throw 'The selected tool signature changed or could not be verified. No tool was run.' }
    Write-Host ('Run as administrator: ' + $selected.Tool) -ForegroundColor Cyan
    Write-Host 'Approve the Windows UAC request and complete any Vector registration dialog.'
    # This is the interactive Vector utility; keep its own dialogs visible.
    $registrar = Start-Process -FilePath $selected.Tool -WorkingDirectory ([IO.Path]::GetDirectoryName($selected.Tool)) -Verb RunAs -WindowStyle Normal -Wait -PassThru
    Write-Host ('Registration tool exit code: ' + $registrar.ExitCode)
    if ($registrar.ExitCode -ne 0) { Write-Host 'The tool did not report success.' -ForegroundColor Red; return 5 }
    $after = Get-CanoeServer -View Registry64
    Write-Host ('Current 64-bit COM server: ' + $(if ($after) { $after } else { '(not registered)' }))
    if (-not $after -or -not (Test-Path -LiteralPath $after -PathType Leaf)) { throw 'The 64-bit CANoe COM server is still missing. Keep this log and contact your PC administrator.' }
    $registered = Get-CanoeVersion -Path $after
    if ($registered.FileMajorPart -ne 19 -or -not [string]::Equals([IO.Path]::GetFullPath($after),[IO.Path]::GetFullPath($selected.Application),[StringComparison]::OrdinalIgnoreCase)) {
        throw 'COM registration still points to another installation. Keep this log; do not delete CANoe versions or edit the registry manually.'
    }
    Write-Host 'SUCCESS: 64-bit CANoe COM now points to the chosen CANoe 19.' -ForegroundColor Green
    Write-Host 'Open One Click Log, choose your CFG, and press Check connection.'
    Write-Host 'This result confirms registration only, not measurement, licensing or vehicle logging.'
    return 0
}


function Test-NpcapInstalled {
    $windows = [Environment]::GetFolderPath('Windows')
    foreach ($name in @('System32\Npcap\wpcap.dll', 'System32\Npcap\Packet.dll', 'System32\drivers\npcap.sys')) {
        if (-not (Test-Path -LiteralPath (Join-Path $windows $name) -PathType Leaf)) { return $false }
    }
    return $true
}

function Get-NpcapInstaller {
    $folder = [IO.Path]::GetDirectoryName($env:ONECLICKLOG_CANOE19_HELPER)
    return Join-Path $folder 'installers\Npcap\npcap-1.90.exe'
}

function Assert-NpcapInstaller {
    param([string]$Path)
    $expected = '682b57e1c05ef375931975c9d6ded40888f4bfdf9f4b11571e654f962f1199b6'
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'Bundled Npcap installer is missing. Extract the complete authorized internal package, or install Npcap through your PC administrator. Standard distributions do not include this installer.'
    }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne 1325256 -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $expected) {
        throw 'Npcap installer size/hash does not match the pinned release. It was NOT executed.'
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch 'Nmap Software LLC') {
        throw 'Npcap installer does not have a valid Nmap Software LLC signature. It was NOT executed.'
    }
}

function Invoke-NpcapSetup {
    param([bool]$CheckOnly)
    Write-Host 'One Click Log - Npcap setup' -ForegroundColor Cyan
    if (Test-NpcapInstalled) {
        Write-Host 'Npcap driver and libraries are already present. Installation skipped.' -ForegroundColor Green
        return 0
    }
    $installer = Get-NpcapInstaller
    Assert-NpcapInstaller -Path $installer
    if ($CheckOnly) {
        Write-Host 'CHECK ONLY: verified the installer; no installation was run.' -ForegroundColor Green
        return 0
    }
    Assert-ToolsClosed
    Write-Host ('Run as administrator: ' + $installer)
    Write-Host 'Approve Windows UAC, review the official license/options and complete the Npcap installer.'
    $process = Start-Process -FilePath $installer -WorkingDirectory ([IO.Path]::GetDirectoryName($installer)) -Verb RunAs -WindowStyle Normal -Wait -PassThru
    if ($process.ExitCode -eq 3010) {
        Write-Host 'Npcap requests a Windows restart. Restart before checking capture.' -ForegroundColor Yellow
        return 3010
    }
    if ($process.ExitCode -ne 0) { throw ('Npcap installer failed or was cancelled. Exit code: ' + $process.ExitCode) }
    if (-not (Test-NpcapInstalled)) { throw 'Npcap files are still missing. Installation is unconfirmed; keep this log and contact your PC administrator.' }
    Write-Host 'Npcap files verified. Check capture access in One Click Log after setup.' -ForegroundColor Green
    return 0
}

function Invoke-InitialSetup {
    param([bool]$CheckOnly)
    if (-not $CheckOnly) { Assert-ToolsClosed }
    $canoe = 1; $npcap = 1
    try { $canoe = Invoke-Canoe19Registration -CheckOnly $CheckOnly }
    catch { Write-Host ('CANoe setup error: ' + $_.Exception.Message) -ForegroundColor Red }
    try { $npcap = Invoke-NpcapSetup -CheckOnly $CheckOnly }
    catch { Write-Host ('Npcap setup error: ' + $_.Exception.Message) -ForegroundColor Red }
    Write-Host ('Setup results - CANoe: {0}; Npcap: {1}' -f $canoe,$npcap)
    Write-Host 'Registration/installation checks do not confirm licensing, measurement or vehicle capture.'
    if ($npcap -eq 3010) { return 3010 }
    if ($canoe -ne 0 -or $npcap -ne 0) { return 1 }
    return 0
}

$taskExitCode = 1
$taskTranscript = $false
try {
    $mode = [string]$env:ONECLICKLOG_CANOE19_MODE
    if ($mode -and $mode -ne '--check') { throw 'Unknown option. Double-click for initial setup, or use --check for discovery only.' }
    $logFolder = Join-Path ([IO.Path]::GetTempPath()) 'OneClickLog-InitialSetup'
    [void][IO.Directory]::CreateDirectory($logFolder)
    $logPath = Join-Path $logFolder ('InitialSetup_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8) + '.txt')
    try { Start-Transcript -LiteralPath $logPath | Out-Null; $taskTranscript = $true } catch { Write-Host ('Could not save a transcript: ' + $_.Exception.Message) -ForegroundColor Yellow }
    $taskExitCode = Invoke-InitialSetup -CheckOnly ($mode -eq '--check')
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Keep the step results above. A cancelled administrator request affects that step.'
    $taskExitCode = 1
} finally {
    if ($taskTranscript) {
        Write-Host ('Log saved: ' + $logPath)
        Stop-Transcript | Out-Null
    }
}
exit $taskExitCode
