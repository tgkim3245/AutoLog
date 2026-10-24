# 개발 안내

기준 SW 0.9.21 · 검토 2026-10-25

제품명은 One Click Log이며 내부 Python 패키지명 `vil_logging`은 유지합니다. 앱 소스는 `src/vil_logging`, 개발 보조 명령은 `tools`, 실제 배포 가이드는 `user_guide`입니다. [폴더별 책임](docs/reference/project_structure.md)과 [문서 목차](docs/README.md)를 따릅니다.

## 개발 환경

Python 3.14 x64의 일반 빌드를 사용합니다. 정확한 의존성은 `requirements.lock`, 허용 범위는 `pyproject.toml`을 기준으로 합니다. 환경 정리 작업을 이유로 기존 Python·CANoe·Npcap을 삭제하거나 업그레이드하지 않습니다.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e .
.\run_demo.cmd
```

`run.cmd`와 `build.cmd`는 프로젝트 가상환경을 우선 사용하고 기존 AppData 개발 환경도 찾습니다. 일반 앱 프로필은 `%LOCALAPPDATA%\One Click Log`, 모의 앱은 그 아래 `demo`로 분리합니다. 검증 명령은 새 `--data-dir`를 사용하고 실제 사용자 프로필을 시험 fixture로 쓰지 않습니다.

## 변경 확인

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src tests packaging tools
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe tools/check_docs.py
.\.venv\Scripts\python.exe tools/build_vehicle_test_document.py --check
```

기본 pytest 범위는 `tests/unit`과 `tests/integration`입니다. COM 대역·생성 파일·테스트 자식 프로세스 결과를 실제 CANoe/VN/차량 수신 성공으로 표현하지 않습니다. `tests/hardware/verify_ethernet_ui.py`도 명시적으로 실행하는 localhost UI 검사이며 이름만으로 물리 NIC 시험으로 간주하지 않습니다.

소스 실행 smoke는 `run.cmd --smoke-test --smoke-debug-log`로 수행할 수 있습니다. 실제 수신·정지·재실행은 [48개 실차 TC](docs/testing/vehicle_test_plan.md)와 [CANoe 준비 점검](docs/testing/licensed_canoe_validation.md)에 따릅니다.

## 명시적 localhost 검증

실제 TShark를 쓰지만 물리 NIC·업무 cfg는 열지 않습니다. 사용할 도구를 명시하고 아직 없는 새 폴더를 지정합니다.

```powershell
.\run.cmd --verify-ethernet --tshark "C:\Program Files\Wireshark\tshark.exe" --data-dir "$env:TEMP\OneClickLog-ethernet-new"
.\run.cmd --verify-file-management --data-dir "$env:TEMP\OneClickLog-files-new"
```

`--verify-monitoring`, `--verify-recovery`, `--verify-load`도 TShark 전체 경로가 필요합니다. 경로는 기존 설치본 또는 배포물의 `tools/Wireshark/tshark.exe`를 실제로 확인해 지정합니다. 생성된 결과와 원본은 Git 제외 폴더에 둡니다.

## 빌드

```powershell
.\build.cmd
.\build.cmd --no-pause --check
.\build.cmd --output-root "D:\OneClickLog_Builds"
# 확인된 사내 PC 1대용 별도 패키지
.\build.cmd --include-npcap-internal
```

Documents 안에서는 기본 `%USERPROFILE%\Downloads\OneClickLog_Builds`, 그 외에는 프로젝트 `outputs`를 사용하며 쓰기가 보호돼 있으면 다운로드 위치를 사용합니다. 실제 위치는 빌드 화면에서 확인합니다. 예시 빌드 ID와 구조는 다음과 같습니다.

```text
One Click Log-0.9.21_YYYYMMDD_HHMMSS/
  One Click Log/
    One Click Log.exe
    _internal/
    tools/Wireshark/
    licenses/
    third_party_sources/
    One Click Log_User_Guide.html
    START_HERE.txt
    build_info.json
  One Click Log-0.9.21_YYYYMMDD_HHMMSS.zip
  One Click Log-0.9.21_YYYYMMDD_HHMMSS.zip.sha256.txt
  build_info.json
  build.log
```

EXE와 동봉 폴더 전체 또는 ZIP을 전달합니다. SW 버전은 `src/vil_logging/__init__.py` 한 곳에서 변경합니다. 같은 버전 재빌드도 기존 산출물을 덮어쓰지 않습니다. Git 커밋·작업 트리 변경 여부·도구/문서 해시는 build_info에 기록됩니다. 코드나 문서를 수정해도 이전 EXE/ZIP이 자동 갱신되지는 않습니다.

Wireshark CLI는 `packaging/wireshark.lock.json`의 고정 버전·크기·SHA256과 vendor 자료로 준비하고 캐시 검증 후 재사용합니다. Wireshark GUI·드라이버를 일반 빌드에 설치하지 않습니다. Npcap 설치기 동봉은 [확인된 내부 PC 범위](docs/guides/npcap_internal_installer.md)의 명시적 옵션이며 실제 설치는 대상 PC 사용자가 합니다. 외부 도구·라이선스 자료를 임의 삭제하지 않습니다.

## 문서와 가이드 유지

현재 정책은 `docs/reference`, 설치/오류 안내는 `docs/guides`, 검증 절차는 `docs/testing`에 둡니다. 버전별 변경·배포 검증은 `docs/updates`, 초기 개발/계획은 `docs/archive`에 둡니다. 과거 기록에 현재 구현을 덮어쓰지 말고 현재 문서로 연결합니다.

사용자에게 보이는 동작·설정·준비 조건·파일/복구·실제 검증 범위가 바뀌면 [공식 관리 흐름](user_guide/README.md)에 따라 HTML 원본·세 언어 번역·배포 안내·메타데이터·이력을 함께 검토합니다. 가이드 검토 버전 불일치, 누락된 사진/번역/좌표, 치환자·해시 오류는 빌드 차단 사유입니다. 검사를 우회하지 않습니다.

[실차 TC Markdown](docs/testing/vehicle_test_plan.md)을 고치면 다음 명령으로 입력형 HTML을 재생성합니다. 기존 회차 결과는 JSON으로 별도 보존합니다.

```powershell
.\.venv\Scripts\python.exe tools/build_vehicle_test_document.py
```

문서 링크와 생성물 최신성도 위 검사로 확인합니다. 개발용 `.venv`·캐시·`outputs`와 사용자 캡처·DB·실제 로그/ZIP·업무 cfg는 커밋하지 않습니다. 성과 수치도 측정 근거 없이 채우지 않습니다.

## Git 반영

기존 저장소의 origin을 사용하며 다시 초기화하지 않습니다. 작업 시작/종료 시 상태를 확인하고 변경 파일만 스테이징합니다. 테스트·문서 이동·링크 수정은 같은 변경에서 검증합니다.

```powershell
git status --short --branch
git add -- AGENTS.md README.md CONTRIBUTING.md docs tools src tests user_guide outputs/README.md
git diff --cached --check
git diff --cached --stat
git commit -m "Describe the final change"
git push origin main
```

삭제할 때는 추적 파일의 실제 사용처와 대체 문서를 확인합니다. demo worker·복구 코드·CLI 진단·테스트 fixture는 사용자 화면에 없다는 이유만으로 제거하지 않습니다. 로컬 산출물이나 사용자 원본을 정리 대상에 섞지 않습니다.
