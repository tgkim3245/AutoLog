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

## 빌드

개발 환경을 준비한 뒤 프로젝트 루트에서 Windows 폴더 배포본을 생성합니다. 빌드 사양은 `packaging/app.spec`이며 산출물과 PyInstaller 작업 파일은 `outputs/` 아래에 둡니다.

```powershell
$buildPython = Join-Path $PWD '.venv\Scripts\python.exe'
$buildOutput = Join-Path $PWD 'outputs\dev'
$buildWork = Join-Path $PWD 'outputs\build'
New-Item -ItemType Directory -Force -Path $buildOutput, $buildWork | Out-Null
& $buildPython -m PyInstaller --noconfirm --workpath $buildWork --distpath $buildOutput packaging\app.spec
```

배포 폴더는 `outputs/dev/AutoLog/`입니다. EXE와 `_internal/`을 포함한 폴더 전체를 함께 사용합니다. `outputs/`의 과거 EXE는 소스 변경으로 갱신되지 않습니다. 배포 전에는 버전, 실행 흐름, 개발자 로그 경로 및 외부 도구 검색 결과를 확인하고 검증 범위를 릴리스 문서에 기록합니다.

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
