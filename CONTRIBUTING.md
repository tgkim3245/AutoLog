# 개발 안내

## 프로젝트 기준

- 제품명은 **AutoLog**이며 Python 패키지와 import 경로는 기존 호환성을 위해 `vil_logging`을 사용합니다.
- 앱 코드는 `src/vil_logging/` 아래에서 관리합니다. Python 화면 코드는 `src/vil_logging/ui/`, HTML 화면 시안은 `docs/design/wireframe.html`에 있습니다.
- 장비가 필요 없는 검사는 `tests/unit/`과 `tests/integration/`에 둡니다. 실제 CANoe, NIC, TShark 장비 검증은 `tests/hardware/`에 분리합니다.
- `.venv/`, `outputs/`, 로컬 설정과 업무 원본은 Git에 올리지 않습니다. 배포·검증 결과가 필요하면 `outputs/`에 보관하고, 재현 가능한 절차와 요약을 문서에 기록합니다.
- 사용자 PC별 설정은 `%LOCALAPPDATA%\AutoLog`에 저장합니다. 비밀값, CANoe 구성 원본, 실제 캡처·진단 로그를 저장소에 추가하지 않습니다.

## Windows 개발 환경

Python 3.14 x64가 필요합니다. 프로젝트 루트에서 PowerShell로 로컬 가상환경을 준비합니다.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e .
```

`run.cmd`는 프로젝트 `.venv`를 우선 사용합니다. 모의 화면은 `run_demo.cmd`, 일반 앱은 `run.cmd`로 실행합니다. 로컬 환경이 준비되지 않은 PC에서는 `run.cmd`가 기존 `%LOCALAPPDATA%` 개발 환경도 찾습니다.

## 변경 확인

코드 변경 후 장비 없는 기본 검사와 정적 검사를 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src tests
```

`tests/hardware/` 검사는 차량 장비가 연결된 시험 PC에서 선택하여 수행합니다. 기본 검사에서는 실제 CANoe 설정 파일과 차량 네트워크를 열지 않습니다.

## 명시적 localhost 검증

실제 TShark를 사용하지만 물리 NIC와 CANoe는 열지 않습니다. 사용할 설치 경로를 명시해야 하며 일반 앱에서 기억한 프로필을 변경하지 않습니다. `--data-dir`는 아직 없는 새 폴더를 지정합니다.

```powershell
.\.venv\Scripts\python.exe -m vil_logging --verify-ethernet --tshark "C:\Program Files\Wireshark\tshark.exe" --data-dir "$env:TEMP\AutoLog-ethernet-new"
```

`--verify-monitoring`, `--verify-recovery`, `--verify-load`도 `--tshark`가 필요합니다. `--verify-file-management`는 외부 도구 없이 생성된 파일만 사용합니다. 차량 시험은 [라이선스 CANoe 검증](docs/licensed_canoe_validation.md)을 따릅니다.

## 빌드

개발 환경을 준비한 뒤 루트의 **`build.cmd`를 더블클릭**하면 Windows 배포 폴더와 ZIP을 자동으로 만듭니다. 현재 작업 디렉터리와 관계없이 프로젝트 경로를 찾고, `run.cmd`처럼 프로젝트 가상환경 또는 기존 AppData 개발 환경을 사용합니다.

```powershell
.\build.cmd
# 환경과 버전만 확인하는 자동화용 실행
.\build.cmd --no-pause --check
```

**SW 버전은 `src/vil_logging/__init__.py`의 `__version__` 한 곳에서 변경합니다.** 프로젝트 패키지 버전, 앱 표시 버전, EXE 파일 속성과 출력 폴더명이 같은 값을 사용합니다. 빌드 시 버전을 자동 증가시키지는 않습니다.

```text
AutoLog-0.4.5_20261018_153000/
├─ AutoLog/
│  ├─ AutoLog.exe
│  ├─ _internal/
│  ├─ START_HERE.txt
│  ├─ AutoLog_User_Guide.html
│  └─ build_info.json
├─ AutoLog-0.4.5_20261018_153000.zip
├─ AutoLog-0.4.5_20261018_153000.zip.sha256.txt
├─ build_info.json
└─ build.log
```

폴더명 뒤 날짜·시각은 같은 버전의 재빌드를 구분합니다. 기존 결과는 덮어쓰지 않습니다. EXE와 `_internal/`을 포함한 `AutoLog/` 전체 또는 생성한 ZIP을 배포합니다. `build_info.json`에는 SW 버전, 빌드 시각, Git 커밋·미커밋 변경 여부와 해시를 기록합니다. 오류 원문은 해당 폴더의 `build.log`에서 확인합니다.

프로젝트가 사용자 `Documents` 안에 있으면 보호 폴더 쓰기를 시도하지 않고 `%USERPROFILE%\Downloads\AutoLog_Builds\` 아래에 저장합니다. 그 외에는 프로젝트 `outputs/`를 사용하며, 폴더 쓰기 보호가 확인되면 다운로드 위치를 사용합니다. 이 PC에서 확인된 제어된 폴더 액세스 차단도 이 방식으로 처리하며 보안 설정은 변경하지 않습니다. 실제 결과 경로는 실행 화면과 빌드 로그에 표시합니다. 위치를 직접 정하려면 `build.cmd --output-root "D:\AutoLog_Builds"`를 사용합니다.

빌드 로직은 `packaging/build_release.py`, PyInstaller 사양은 `packaging/app.spec`입니다. 중간 분석 파일은 선택된 산출물 위치의 `build/<빌드명>/`에 남겨 빌드 오류 확인에 사용합니다. 실행·빌드 결과는 Git에서 제외합니다. 배포 전 실행 흐름과 장비 연동을 확인하고 검증 범위를 릴리스 문서에 기록합니다.

## 배포용 사용자 가이드 갱신

사용자 동작·도구/라이선스·Defender 허용 앱·파일/복구·검증 범위가 바뀌면 [공식 가이드 관리 원본](user_guide/README.md)을 같은 변경에서 수정합니다. HTML 템플릿과 배포 안내문을 검토하고 `guide_metadata.json`의 적용 SW 버전·문서 개정·갱신일, `CHANGELOG.md`를 함께 갱신합니다. `AGENTS.md`에도 이 유지 규칙을 기록했습니다.

빌드는 `AutoLog_User_Guide.html`과 `START_HERE.txt`를 EXE 옆과 ZIP에 넣습니다. `build_info.json`의 `documentation`에 적용 버전·개정·갱신일·파일별 크기/SHA256을 기록합니다. 가이드 누락·검토 버전 불일치·잘못된 개정 정보·남은 템플릿 치환자는 빌드 전에 오류로 처리하며 `--check`에서도 확인합니다. 문서만 변경한 경우 SW 버전은 유지하고 문서 개정과 새로운 빌드 시각으로 구분합니다.

배포 전 두 문서를 압축 해제본에서 열어 읽고, HTML의 목차·Defender 절차·실제 사용 절차와 버전 표시를 확인하세요. 과거 개발 초안이나 발표 자료는 사용자 안내 대신 배포하지 않습니다.

## Git 작업

이 프로젝트는 이미 `origin`이 AutoLog 저장소로 연결되어 있습니다. 기존 작업 폴더에서 `git init`이나 `git remote add origin`을 반복하지 않습니다. `git ls-files src`로 앱 코드가 추적되는지 확인할 수 있습니다.

작업 전후에 `git status --short --branch`를 확인합니다. `??`는 새로 생겼지만 아직 커밋에 포함하지 않은 파일입니다. 실제 변경한 파일을 선택하여 스테이징하고, 변경 내용을 확인한 뒤 커밋합니다. 아래 `git add`는 소스·검사·문서를 수정한 경우의 예시입니다.

```powershell
git status --short --branch
git add -- src tests docs README.md
git diff --cached --check
git diff --cached --stat
git commit -m "Describe the change"
git push
```

한 커밋에는 한 가지 목적의 변경을 담고, 제품 동작 변경은 해당 `docs/hotfix_*.md` 또는 개발 기록을 함께 갱신합니다. `.gitignore`는 산출물과 실제 BLF/PCAP 캡처·진단 로그를 제외합니다. `outputs/README.md`만 산출물 폴더의 안내로 추적합니다.
