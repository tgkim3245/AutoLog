@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "ONECLICKLOG_SETUP_HELPER=%~f0"
set "ONECLICKLOG_SETUP_MODE=%~1"
set "ONECLICKLOG_SETUP_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "ONECLICKLOG_SETUP_POWERSHELL=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%ONECLICKLOG_SETUP_POWERSHELL%" -NoLogo -NoProfile -Command "$text=[IO.File]::ReadAllText($env:ONECLICKLOG_SETUP_HELPER,[Text.Encoding]::UTF8); $mark='# POWERSHELL_PAYLOAD_BEGIN'; $pos=$text.LastIndexOf($mark); if($pos -lt 0){exit 90}; & ([scriptblock]::Create($text.Substring($pos+$mark.Length)))"
set "ONECLICKLOG_SETUP_RESULT=%errorlevel%"
echo.
if /i "%ONECLICKLOG_SETUP_MODE%"=="--check" goto finish
pause
:finish
exit /b %ONECLICKLOG_SETUP_RESULT%
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

function Add-CanoeSearchRoot {
    param($Roots, [string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    $pathValue = [Environment]::ExpandEnvironmentVariables($Path).Trim('"')
    if (Test-Path -LiteralPath $pathValue -PathType Leaf) { $pathValue = [IO.Path]::GetDirectoryName($pathValue) }
    if (Test-Path -LiteralPath $pathValue -PathType Container) { [void]$Roots.Add([IO.Path]::GetFullPath($pathValue)) }
}

function Get-CanoeSearchRoots {
    $roots = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($programFolder in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432)) {
        if ([string]::IsNullOrWhiteSpace($programFolder) -or -not (Test-Path -LiteralPath $programFolder -PathType Container)) { continue }
        foreach ($folder in @(Get-ChildItem -LiteralPath $programFolder -Directory -Filter '*CANoe*' -ErrorAction SilentlyContinue)) {
            Add-CanoeSearchRoot -Roots $roots -Path $folder.FullName
        }
        foreach ($vendor in @('Vector', 'Vector Informatik')) {
            $vendorFolder = Join-Path $programFolder $vendor
            if (-not (Test-Path -LiteralPath $vendorFolder -PathType Container)) { continue }
            foreach ($folder in @(Get-ChildItem -LiteralPath $vendorFolder -Directory -Filter '*CANoe*' -ErrorAction SilentlyContinue)) {
                Add-CanoeSearchRoot -Roots $roots -Path $folder.FullName
            }
        }
    }
    foreach ($hive in @([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryHive]::CurrentUser)) {
        foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
            $base = $null
            try {
                $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
                foreach ($branch in @('SOFTWARE\Vector\CANoe', 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall')) {
                    $parent = $base.OpenSubKey($branch)
                    if ($null -eq $parent) { continue }
                    try {
                        foreach ($name in $parent.GetSubKeyNames()) {
                            $entry = $parent.OpenSubKey($name)
                            if ($null -eq $entry) { continue }
                            try {
                                if ($branch.EndsWith('Uninstall') -and [string]$entry.GetValue('DisplayName') -notmatch '\bCANoe\b') { continue }
                                foreach ($valueName in @('Path', 'InstallLocation', 'InstallDir')) {
                                    Add-CanoeSearchRoot -Roots $roots -Path ([string]$entry.GetValue($valueName))
                                }
                            } finally { $entry.Close() }
                        }
                    } finally { $parent.Close() }
                }
            } catch { Write-Host ('Registry discovery warning: ' + $_.Exception.Message) -ForegroundColor Yellow }
            finally { if ($null -ne $base) { $base.Close() } }
        }
    }
    Add-CanoeSearchRoot -Roots $roots -Path (Get-CanoeServer -View Registry64)
    return @($roots | Sort-Object)
}

function Get-CanoeFileTrust {
    param([string]$Path)
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    $trusted = $signature.Status -eq 'Valid' -and $null -ne $signature.SignerCertificate -and $signature.SignerCertificate.Subject -match 'Vector Informatik'
    return [pscustomobject]@{ Status=[string]$signature.Status; TrustedVector=[bool]$trusted; Unsigned=($signature.Status -eq 'NotSigned') }
}

function Test-CanoeTrustCombination {
    param($Tool, $Application)
    return [bool](($Tool.TrustedVector -or $Tool.Unsigned) -and ($Application.TrustedVector -or $Application.Unsigned))
}

function Get-CanoeInstallations {
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $found = @()
    foreach ($root in @(Get-CanoeSearchRoots)) {
        Write-Host ('Search: ' + $root)
        foreach ($application in @(Get-ChildItem -LiteralPath $root -File -Filter CANoe64.exe -Recurse -ErrorAction SilentlyContinue)) {
            if (-not $seen.Add($application.FullName)) { continue }
            try {
                $info = Get-CanoeVersion -Path $application.FullName
                $tool = Join-Path $application.DirectoryName 'RegisterComponents.exe'
                $present = Test-Path -LiteralPath $tool -PathType Leaf
                $toolTrust = [pscustomobject]@{Status='Missing';TrustedVector=$false;Unsigned=$false}
                if ($present) { $toolTrust = Get-CanoeFileTrust -Path $tool }
                $appTrust = Get-CanoeFileTrust -Path $application.FullName
                $confirmUnsigned = (Test-CanoeTrustCombination -Tool $toolTrust -Application $appTrust) -and ($toolTrust.Unsigned -or $appTrust.Unsigned)
                $found += [pscustomobject]@{ Tool=$tool; Application=$application.FullName; Major=$info.FileMajorPart; Version=$info.FileVersion; ToolPresent=$present; TrustedVector=$toolTrust.TrustedVector; TrustedApplication=$appTrust.TrustedVector; ToolSignatureStatus=$toolTrust.Status; ApplicationSignatureStatus=$appTrust.Status; CanConfirmUnsigned=$confirmUnsigned }
            } catch { Write-Host ('Could not inspect ' + $application.FullName + ': ' + $_.Exception.Message) -ForegroundColor Yellow }
        }
    }
    return @($found | Sort-Object @{Expression='Major';Descending=$true}, Version, Application)
}

function Assert-ToolsClosed {
    $running = @(Get-Process -ErrorAction Stop | Where-Object { $_.ProcessName -in @('CANoe','CANoe32','CANoe64','One Click Log','One_Click_Log','AutoLog','Auto_Log') })
    if ($running.Count) {
        $description = ($running | ForEach-Object { '{0} (PID {1})' -f $_.ProcessName,$_.Id }) -join ', '
        throw ('Save your work and close One Click Log and ALL CANoe windows, then run this BAT again. Running: ' + $description)
    }
}

function Invoke-CanoeRegistration {
    param([bool]$CheckOnly)
    Write-Host 'One Click Log - Select the default CANoe for your RBS/CFG' -ForegroundColor Cyan
    Write-Host 'No version is selected automatically. COM registration affects CANoe automation on this PC.'
    $before = Get-CanoeServer -View Registry64
    Write-Host ('Current 64-bit COM server: ' + $(if ($before) { $before } else { '(not registered)' }))
    $candidates = @(Get-CanoeInstallations)
    if (-not $candidates.Count) {
        Write-Host 'No CANoe64.exe installation was found in known installation locations.' -ForegroundColor Yellow
        Write-Host 'No registration tool was run. Install/repair the CANoe version required by your RBS/CFG, or ask your PC administrator.'
        return 2
    }
    for ($index = 0; $index -lt $candidates.Count; $index++) {
        $item = $candidates[$index]
        $current = if ([string]::Equals($before,$item.Application,[StringComparison]::OrdinalIgnoreCase)) { ' [current COM target]' } else { '' }
        Write-Host ('[{0}] CANoe {1} (64-bit){2}' -f ($index+1),$item.Version,$current)
        Write-Host ('    Application: ' + $item.Application)
        Write-Host ('    Registration tool: {0}; present: {1}; signature: {2}; application signature: {3}' -f $item.Tool,$item.ToolPresent,$item.ToolSignatureStatus,$item.ApplicationSignatureStatus)
        if ($item.CanConfirmUnsigned) { Write-Host '    Unsigned file(s): official installation review and an extra REGISTER confirmation are required.' -ForegroundColor Yellow }
    }
    if ($CheckOnly) {
        Write-Host 'CHECK ONLY: no selection, tool execution or COM registration change.' -ForegroundColor Green
        if (@($candidates | Where-Object { $_.ToolPresent -and $_.TrustedVector -and $_.TrustedApplication -and $_.Major -gt 0 }).Count) { return 0 }
        return 3
    }
    Assert-ToolsClosed
    while ($true) {
        $answer = [string](Read-Host ('Enter the LIST NUMBER for the CANoe required by your RBS/CFG (1-{0}), or Enter/Q to cancel' -f $candidates.Count))
        $answer = $answer.Trim()
        if (-not $answer -or $answer -ieq 'q') { Write-Host 'Cancelled. No registration tool was run.'; return 4 }
        $number = 0
        if ([int]::TryParse($answer, [ref]$number) -and $number -ge 1 -and $number -le $candidates.Count) { break }
        Write-Host 'Invalid selection. Enter a list number, not a CANoe version number.' -ForegroundColor Yellow
    }
    $selected = $candidates[$number-1]
    Write-Host ('Chosen: CANoe {0}; {1}' -f $selected.Version,$selected.Application) -ForegroundColor Cyan
    if (-not $selected.ToolPresent) { throw 'The chosen installation has no paired RegisterComponents.exe. Repair this CANoe installation; no other version was substituted.' }
    $unsignedApproved = $false
    $toolHash = ''; $applicationHash = ''
    if (-not $selected.TrustedVector -or -not $selected.TrustedApplication) {
        if (-not $selected.CanConfirmUnsigned) { throw 'The chosen tool/application has an invalid or unverified signature. It was NOT executed.' }
        $toolHash = (Get-FileHash -LiteralPath $selected.Tool -Algorithm SHA256).Hash
        $applicationHash = (Get-FileHash -LiteralPath $selected.Application -Algorithm SHA256).Hash
        Write-Host 'These installed files have no digital signature. The script cannot establish their publisher.' -ForegroundColor Yellow
        Write-Host ('Tool SHA256: ' + $toolHash)
        Write-Host ('Application SHA256: ' + $applicationHash)
        $approval = [string](Read-Host 'Only if you verified this is your official trusted CANoe installation, type REGISTER to continue; otherwise press Enter to cancel')
        if ($approval -cne 'REGISTER') { Write-Host 'Cancelled. No registration tool was run.'; return 4 }
        $unsignedApproved = $true
    }
    Assert-ToolsClosed
    if (-not (Test-Path -LiteralPath $selected.Application -PathType Leaf) -or -not (Test-Path -LiteralPath $selected.Tool -PathType Leaf)) { throw 'The chosen installation changed or disappeared. No tool was run.' }
    $selectedVersion = Get-CanoeVersion -Path $selected.Application
    if ($selected.Major -le 0 -or $selectedVersion.FileMajorPart -ne $selected.Major -or $selectedVersion.FileVersion -ne $selected.Version) { throw 'The chosen CANoe executable version changed. No tool was run.' }
    $toolTrust = Get-CanoeFileTrust -Path $selected.Tool
    $appTrust = Get-CanoeFileTrust -Path $selected.Application
    if ($unsignedApproved) {
        if (-not (Test-CanoeTrustCombination -Tool $toolTrust -Application $appTrust) -or $toolTrust.Status -ne $selected.ToolSignatureStatus -or $appTrust.Status -ne $selected.ApplicationSignatureStatus) { throw 'The selected tool/application signature changed. No tool was run.' }
        if ((Get-FileHash -LiteralPath $selected.Tool -Algorithm SHA256).Hash -ne $toolHash -or (Get-FileHash -LiteralPath $selected.Application -Algorithm SHA256).Hash -ne $applicationHash) { throw 'The unsigned installation hash changed after confirmation. No tool was run.' }
    } elseif (-not $toolTrust.TrustedVector -or -not $appTrust.TrustedVector) { throw 'The selected tool/application signature changed or could not be verified. No tool was run.' }
    Write-Host ('Run as administrator: ' + $selected.Tool) -ForegroundColor Cyan
    Write-Host 'Approve Windows UAC and complete the official Vector registration dialog.'
    $registrar = Start-Process -FilePath $selected.Tool -WorkingDirectory ([IO.Path]::GetDirectoryName($selected.Tool)) -Verb RunAs -WindowStyle Normal -Wait -PassThru
    Write-Host ('Registration tool exit code: ' + $registrar.ExitCode)
    if ($registrar.ExitCode -ne 0) { Write-Host 'The tool did not report success.' -ForegroundColor Red; return 5 }
    $after = Get-CanoeServer -View Registry64
    Write-Host ('Current 64-bit COM server: ' + $(if ($after) { $after } else { '(not registered)' }))
    if (-not $after -or -not (Test-Path -LiteralPath $after -PathType Leaf)) { throw 'The 64-bit CANoe COM server is still missing. Keep this log and contact your PC administrator.' }
    $registered = Get-CanoeVersion -Path $after
    if ($registered.FileMajorPart -ne $selected.Major -or $registered.FileVersion -ne $selected.Version -or -not [string]::Equals([IO.Path]::GetFullPath($after),[IO.Path]::GetFullPath($selected.Application),[StringComparison]::OrdinalIgnoreCase)) {
        throw 'COM registration still points to another installation. Keep this log; do not delete CANoe versions or edit the registry manually.'
    }
    Write-Host ('SUCCESS: 64-bit CANoe COM now points to the chosen CANoe ' + $selected.Version) -ForegroundColor Green
    Write-Host 'Open One Click Log, choose your RBS/CFG, and check the connection.'
    Write-Host 'If the wrong RBS/CFG version fails to open, save/close the app and all CANoe windows, then rerun this BAT and choose the correct version.'
    Write-Host 'Registration does not establish RBS compatibility, licensing, measurement or vehicle capture.'
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
    $folder = [IO.Path]::GetDirectoryName($env:ONECLICKLOG_SETUP_HELPER)
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
    try { $canoe = Invoke-CanoeRegistration -CheckOnly $CheckOnly }
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
    $mode = [string]$env:ONECLICKLOG_SETUP_MODE
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
