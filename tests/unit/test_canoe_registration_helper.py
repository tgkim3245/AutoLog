"""Exercise the standalone registration helper without launching a registrar or writing COM."""

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools/Initial_Setup.bat"
POWERSHELL = (
    Path(os.environ.get("SystemRoot", "C:/Windows"))
    / "System32/WindowsPowerShell/v1.0/powershell.exe"
)
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell BAT helper")

HARNESS = r"""
$ErrorActionPreference='Stop'
Import-Module Microsoft.PowerShell.Utility
Import-Module Microsoft.PowerShell.Management
$payload=[IO.File]::ReadAllText($env:ONECLICKLOG_TEST_HELPER,[Text.Encoding]::UTF8)
$marker='# POWERSHELL_PAYLOAD_BEGIN'
$payload=$payload.Substring($payload.LastIndexOf($marker)+$marker.Length)
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseInput($payload,[ref]$tokens,[ref]$errors)
if($errors.Count){ throw ($errors | Out-String) }
$definitions=$tree.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)
. ([scriptblock]::Create(($definitions | ForEach-Object {$_.Extent.Text}) -join "`n"))
$scenario=$env:ONECLICKLOG_TEST_SCENARIO
$script:launches=0
$script:serverReads=0
$script:prompts=0
$script:chosenMajor=19
$script:chosenPath=''
$script:selectedTool=''
$script:hashReads=0
function Get-CanoeInstallations {
    if($scenario -eq 'missing'){return @()}
    $item=[pscustomobject]@{Tool='C:\Vector19\Exec64\RegisterComponents.exe'; Application='C:\Vector19\Exec64\CANoe64.exe'; Major=19; Version='19.3.118'; ToolPresent=($scenario -ne 'tool_missing'); TrustedVector=($scenario -ne 'untrusted');TrustedApplication=($scenario -ne 'app_untrusted')}
    $unsigned=$scenario -in @('unsigned_confirm','unsigned_cancel','unsigned_changed')
    $item | Add-Member ToolSignatureStatus $(if($unsigned){'NotSigned'}else{'Valid'})
    $item | Add-Member ApplicationSignatureStatus $(if($unsigned){'NotSigned'}else{'Valid'})
    $item | Add-Member CanConfirmUnsigned $unsigned
    if($unsigned){$item.TrustedVector=$false;$item.TrustedApplication=$false}
    $older=[pscustomobject]@{Tool='C:\Vector15\Exec64\RegisterComponents.exe'; Application='C:\Vector15\Exec64\CANoe64.exe'; Major=15; Version='15.0.55'; ToolPresent=$true;TrustedVector=$true;TrustedApplication=$true}
    $older | Add-Member ToolSignatureStatus 'Valid'
    $older | Add-Member ApplicationSignatureStatus 'Valid'
    $older | Add-Member CanConfirmUnsigned $false
    if($scenario -in @('select_older','wrong_target','multiple_cancel','invalid_retry')){return @($item,$older)}
    return @($item)
}
function Get-CanoeServer {
    param($View)
    $script:serverReads++
    if($script:serverReads -eq 1 -or $scenario -eq 'wrong_target'){return 'C:\Vector19\Exec64\CANoe64.exe'}
    if($scenario -eq 'same_version_wrong_target'){return 'C:\Vector19_copy\Exec64\CANoe64.exe'}
    return $script:chosenPath
}
function Get-CanoeVersion {
    param($Path)
    $major=if($Path -like '*Vector15*'){15}else{19}
    $version=if($major -eq 15){'15.0.55'}else{'19.3.118'}
    if($scenario -eq 'version_changed'){$major=20;$version='20.0.1'}
    return [pscustomobject]@{FileMajorPart=$major;FileVersion=$version}
}
function Get-AuthenticodeSignature {
    param($LiteralPath)
    $status=if($scenario -in @('unsigned_confirm','unsigned_cancel','unsigned_changed')){'NotSigned'}elseif($scenario -eq 'signature_changed' -or ($scenario -eq 'app_signature_changed' -and $LiteralPath -like '*CANoe64.exe')){'NotSigned'}else{'Valid'}
    return [pscustomobject]@{Status=$status;SignerCertificate=[pscustomobject]@{Subject='CN=Vector Informatik GmbH'}}
}
function Get-FileHash {param($LiteralPath,$Algorithm) $script:hashReads++; $value=if($scenario -eq 'unsigned_changed' -and $script:hashReads -gt 2){'changed'}else{'stable hash'};return [pscustomobject]@{Hash=$value}}
function Test-Path {param($LiteralPath,$PathType) return ($scenario -ne 'disappeared')}
function Get-Process {
    param($ErrorAction)
    if($scenario -eq 'running'){return [pscustomobject]@{ProcessName='CANoe64';Id=123}}
    return @()
}
function Read-Host {
    param($Prompt)
    $script:prompts++
    if($Prompt -like 'Only if*'){if($scenario -eq 'unsigned_cancel'){return ''};return 'REGISTER'}
    if($scenario -in @('multiple_cancel','single_cancel')){return ''}
    if($scenario -eq 'q_cancel'){return 'Q'}
    if($scenario -eq 'invalid_retry' -and $script:prompts -eq 1){return '19'}
    if($scenario -in @('select_older','wrong_target','invalid_retry')){return '2'}
    return '1'
}
function Start-Process {
    param($FilePath,$WorkingDirectory,$Verb,$WindowStyle,[switch]$Wait,[switch]$PassThru)
    if($FilePath -notin @('C:\Vector19\Exec64\RegisterComponents.exe','C:\Vector15\Exec64\RegisterComponents.exe') -or $Verb -ne 'RunAs' -or $WindowStyle -ne 'Normal' -or -not $Wait -or -not $PassThru){throw 'Unexpected launch parameters'}
    $script:launches++
    $script:selectedTool=$FilePath
    $script:chosenMajor=if($FilePath -like '*Vector15*'){15}else{19}
    $script:chosenPath=if($script:chosenMajor -eq 15){'C:\Vector15\Exec64\CANoe64.exe'}else{'C:\Vector19\Exec64\CANoe64.exe'}
    if($scenario -eq 'uac_cancel'){throw 'Administrator approval cancelled'}
    $code=if($scenario -eq 'tool_failed'){9}else{0}
    return [pscustomobject]@{ExitCode=$code}
}
$result=@{error='';code=-1;launches=0}
try {$result.code=Invoke-CanoeRegistration -CheckOnly ($scenario -eq 'check')}
catch {$result.code=1;$result.error=$_.Exception.Message}
$result.launches=$script:launches
$result.prompts=$script:prompts
$result.selectedTool=$script:selectedTool
Write-Output ('HELPER_TEST_RESULT='+($result|ConvertTo-Json -Compress))
"""


@pytest.mark.parametrize(
    ("scenario", "code", "launches", "error_text"),
    [
        ("check", 0, 0, ""),
        ("missing", 2, 0, ""),
        ("running", 1, 0, "close"),
        ("untrusted", 1, 0, "signature"),
        ("signature_changed", 1, 0, "signature"),
        ("version_changed", 1, 0, "version changed"),
        ("multiple_cancel", 4, 0, ""),
        ("uac_cancel", 1, 1, "cancelled"),
        ("tool_failed", 5, 1, ""),
        ("wrong_target", 1, 1, "another installation"),
        ("success", 0, 1, ""),
        ("select_older", 0, 1, ""),
        ("unsigned_confirm", 0, 1, ""),
        ("unsigned_cancel", 4, 0, ""),
        ("unsigned_changed", 1, 0, "hash changed"),
        ("same_version_wrong_target", 1, 1, "another installation"),
        ("invalid_retry", 0, 1, ""),
        ("single_cancel", 4, 0, ""),
        ("q_cancel", 4, 0, ""),
        ("tool_missing", 1, 0, "no paired"),
        ("app_untrusted", 1, 0, "signature"),
        ("app_signature_changed", 1, 0, "signature"),
        ("disappeared", 1, 0, "disappeared"),
    ],
)
def test_registration_guards_with_only_mocked_system_actions(scenario, code, launches, error_text):
    encoded = base64.b64encode(HARNESS.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [str(POWERSHELL), "-NoLogo", "-NoProfile", "-EncodedCommand", encoded],
        env={
            **os.environ,
            "ONECLICKLOG_TEST_HELPER": str(HELPER),
            "ONECLICKLOG_TEST_SCENARIO": scenario,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    line = next(
        line for line in result.stdout.splitlines() if line.startswith("HELPER_TEST_RESULT=")
    )
    outcome = json.loads(line.partition("=")[2])
    assert outcome["code"] == code, outcome
    assert outcome["launches"] == launches, outcome
    assert error_text.casefold() in outcome["error"].casefold(), outcome
    if scenario in {"select_older", "invalid_retry"}:
        assert "Vector15" in outcome["selectedTool"]
    if scenario == "success":
        assert outcome["prompts"] == 1  # A single installation still needs explicit selection.
    if scenario == "check":
        assert outcome["prompts"] == 0
    if scenario == "invalid_retry":
        assert outcome["prompts"] == 2


def test_bat_launcher_check_handles_spaces_and_shell_characters(tmp_path):
    folder = tmp_path / "helper & space ! ' 한글 test"
    folder.mkdir()
    helper = folder / HELPER.name
    helper.write_bytes(HELPER.read_bytes())
    result = subprocess.run(
        f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c ""{helper}" --check"',
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    # Machines without a signed CANoe installation may return missing/untrusted.
    assert result.returncode in {0, 1}, result.stdout + result.stderr
    assert "CHECK ONLY" in result.stdout or "No CANoe64.exe installation" in result.stdout


NPCAP_HARNESS = (
    HARNESS.split("$scenario=")[0]
    + r"""
$scenario=$env:ONECLICKLOG_TEST_SCENARIO
$script:launches=0
function Test-NpcapInstalled { return ($scenario -eq 'installed' -or ($script:launches -gt 0 -and $scenario -ne 'postmissing')) }
function Get-NpcapInstaller { return 'C:\package\installers\Npcap\npcap-1.90.exe' }
function Test-Path {param($LiteralPath,$PathType) return ($scenario -ne 'missing')}
function Get-Item {param($LiteralPath) return [pscustomobject]@{Length=1325256}}
function Get-FileHash {
    param($LiteralPath,$Algorithm)
    $hash=if($scenario -eq 'hash'){'tampered'}else{'682b57e1c05ef375931975c9d6ded40888f4bfdf9f4b11571e654f962f1199b6'}
    return [pscustomobject]@{Hash=$hash}
}
function Get-AuthenticodeSignature {
    param($LiteralPath)
    $status=if($scenario -eq 'signature'){'NotSigned'}else{'Valid'}
    return [pscustomobject]@{Status=$status;SignerCertificate=[pscustomobject]@{Subject='CN=Nmap Software LLC'}}
}
function Get-Process {
    param($ErrorAction)
    if($scenario -eq 'running'){return [pscustomobject]@{ProcessName='CANoe64';Id=123}}
    return @()
}
function Start-Process {
    param($FilePath,$WorkingDirectory,$Verb,$WindowStyle,[switch]$Wait,[switch]$PassThru)
    if($FilePath -ne 'C:\package\installers\Npcap\npcap-1.90.exe' -or $Verb -ne 'RunAs' -or $WindowStyle -ne 'Normal' -or -not $Wait -or -not $PassThru){throw 'Unexpected launch parameters'}
    $script:launches++
    if($scenario -eq 'cancel'){throw 'Administrator approval cancelled'}
    $code=if($scenario -eq 'failed'){9}elseif($scenario -eq 'reboot'){3010}else{0}
    return [pscustomobject]@{ExitCode=$code}
}
$result=@{error='';code=-1;launches=0}
try {$result.code=Invoke-NpcapSetup -CheckOnly ($scenario -eq 'check')}
catch {$result.code=1;$result.error=$_.Exception.Message}
$result.launches=$script:launches
Write-Output ('HELPER_TEST_RESULT='+($result|ConvertTo-Json -Compress))
"""
)


@pytest.mark.parametrize(
    ("scenario", "code", "launches", "error_text"),
    [
        ("installed", 0, 0, ""),
        ("check", 0, 0, ""),
        ("missing", 1, 0, "missing"),
        ("hash", 1, 0, "hash"),
        ("signature", 1, 0, "signature"),
        ("running", 1, 0, "close"),
        ("cancel", 1, 1, "cancelled"),
        ("failed", 1, 1, "Exit code"),
        ("reboot", 3010, 1, ""),
        ("postmissing", 1, 1, "unconfirmed"),
        ("success", 0, 1, ""),
    ],
)
def test_npcap_installation_with_only_mocked_system_actions(scenario, code, launches, error_text):
    encoded = base64.b64encode(NPCAP_HARNESS.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [str(POWERSHELL), "-NoLogo", "-NoProfile", "-EncodedCommand", encoded],
        env={
            **os.environ,
            "ONECLICKLOG_TEST_HELPER": str(HELPER),
            "ONECLICKLOG_TEST_SCENARIO": scenario,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    line = next(
        line for line in result.stdout.splitlines() if line.startswith("HELPER_TEST_RESULT=")
    )
    outcome = json.loads(line.partition("=")[2])
    assert outcome["code"] == code, outcome
    assert outcome["launches"] == launches, outcome
    assert error_text.casefold() in outcome["error"].casefold(), outcome


def test_npcap_helper_pin_matches_distribution_lock():
    lock = json.loads((ROOT / "packaging/npcap.lock.json").read_text(encoding="utf-8"))
    script = HELPER.read_text(encoding="ascii")
    assert lock["installer"]["sha256"] in script
    assert str(lock["installer"]["bytes"]) in script
    assert lock["installer"]["name"] in script


@pytest.mark.parametrize("missing_tool", [False, True])
def test_discovery_finds_multiple_versions_and_deduplicates_overlapping_roots(
    tmp_path, missing_tool
):
    for version in (15, 19):
        folder = tmp_path / f"Vector CANoe {version}" / "Exec64"
        folder.mkdir(parents=True)
        (folder / "CANoe64.exe").write_bytes(b"discovery fixture; never executed")
        if not (missing_tool and version == 15):
            (folder / "RegisterComponents.exe").write_bytes(b"discovery fixture; never executed")
    harness = (
        HARNESS.split("$scenario=")[0]
        + r"""
function Get-CanoeSearchRoots {return @($env:ONECLICKLOG_DISCOVERY_ROOT,(Join-Path $env:ONECLICKLOG_DISCOVERY_ROOT 'Vector CANoe 19'))}
function Get-CanoeVersion {param($Path) $major=if($Path -like '*CANoe 15*'){15}else{19};return [pscustomobject]@{FileMajorPart=$major;FileVersion=([string]$major+'.0.1')}}
function Get-AuthenticodeSignature {param($LiteralPath) return [pscustomobject]@{Status='Valid';SignerCertificate=[pscustomobject]@{Subject='CN=Vector Informatik GmbH'}}}
$found=@(Get-CanoeInstallations | Select-Object Major,Version,ToolPresent,TrustedVector,TrustedApplication,Application)
Write-Output ('DISCOVERY_RESULT='+($found|ConvertTo-Json -Compress))
"""
    )
    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-EncodedCommand",
            base64.b64encode(harness.encode("utf-16le")).decode("ascii"),
        ],
        env={
            **os.environ,
            "ONECLICKLOG_TEST_HELPER": str(HELPER),
            "ONECLICKLOG_DISCOVERY_ROOT": str(tmp_path),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("DISCOVERY_RESULT="))
    found = json.loads(line.partition("=")[2])
    assert [item["Major"] for item in found] == [19, 15]
    assert found[0]["ToolPresent"] and found[0]["TrustedApplication"]
    assert found[1]["ToolPresent"] is (not missing_tool)
    assert found[1]["TrustedVector"] is (not missing_tool)
