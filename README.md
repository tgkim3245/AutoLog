# AutoLog

Windows용 CANoe/Wireshark 로깅 제어 앱입니다. CAN, Diag, Zipy 대상을 선택하고 공통 logging 버튼으로 기록을 제어합니다.

현재 소스 버전은 **0.6.0**입니다. [미완료 기록 복구와 사용 순서](docs/development_stage_6.md), [대표 구성 수정 결과](docs/canoe_fix_plan.md), [개발 안내](CONTRIBUTING.md)를 참고하세요.

비정상 종료 후에는 메인의 **미완료 확인 N건** 또는 **파일 관리 → 미완료 기록 복구**에서 파일을 검토합니다. 외부 기록 종료를 직접 확인한 뒤 **검사 후 보관**하거나 **파일 유지하고 미완료 정리**할 수 있습니다. 파일과 소비한 번호를 유지하며 복구 세션은 실패 이력으로 남깁니다.

대표 두 .cfg의 독립 연결은 CANoe 19.3.118에서 확인했습니다. CAN+Diag 사용 전 **설정 → CAN·Diag 구성 → CANoe 독립 연결 설정…**에서 다중 연결을 적용하세요. 모든 CANoe 창이 닫힌 상태에서 원본 can.ini를 백업하고 적용하며, 기본 연결로 복구할 수 있습니다. 현재 PC는 **View Only**이므로 라이선스 활성화 후 실제 구간 기록·장비 검증이 남아 있습니다. [최초 검토](docs/cfg_compatibility_review.md)와 [후속 수정 결과](docs/canoe_fix_plan.md)를 구분합니다.

## 폴더와 Git 관리 범위

| 위치 | 역할 | Git 관리 |
| --- | --- | --- |
| `src/vil_logging/` | 실제 Python 앱 소스. 메인 화면은 `ui/main_window.py`, 실행 진입점은 `app.py` | 포함 |
| `tests/` | 단위·통합 검사와 시험 PC용 장비 검사 | 포함 |
| `packaging/app.spec` | 소스에서 Windows EXE를 만드는 PyInstaller 사양 | 포함 |
| `build.cmd` | 버전별 EXE 폴더와 배포 ZIP을 만드는 자동 빌드 실행 파일 | 포함 |
| `docs/` | 요구사항, 설계, 개발 이력, 시험 PC 준비 안내 | 포함 |
| `docs/design/wireframe.html` | 과거 HTML 화면 시안. 실행 앱의 UI 소스는 `src/vil_logging/ui/` | 포함 |
| `user_guide/` | 사용자 가이드와 성과·발표 자료 | 포함 |
| `licenses/` | 배포에 필요한 외부 라이선스 고지 | 포함 |
| `outputs/` | 이전 EXE 배포본, ZIP, 검증 JSON·이미지, 외부 도구 설치 파일 | 안내 README만 포함 |
| `.venv/`, `developer_logs/` | 로컬 개발 환경과 소스 실행 시 생성하는 진단 로그 | 제외 |

프로젝트 정의와 허용 의존성 범위는 `pyproject.toml`, 개발 PC의 정확한 패키지 버전은 `requirements.lock`에 있습니다. 제품 표시명은 AutoLog이며 Python 내부 패키지명은 기존 `vil_logging`을 유지합니다.

실제 수정 대상은 `src/vil_logging/`입니다. `outputs/`의 EXE는 만들어진 시점의 프로그램이므로 소스를 고쳐도 바뀌지 않습니다. 배포하려면 다시 빌드해야 합니다. 과거 단계 문서의 `outputs/` 링크는 로컬 검증 자료를 가리키며, GitHub에서 새로 복제하면 해당 산출물은 포함되지 않습니다.

## 실행과 빌드

개발 환경을 준비한 뒤 프로젝트 루트에서 실행합니다.

```powershell
.\run.cmd
# 실제 캡처 없이 모의 동작 확인
.\run_demo.cmd
```

Python 3.14 x64 환경 준비와 검사 절차는 [개발 안내](CONTRIBUTING.md)에 있습니다. `run.cmd`는 프로젝트 `.venv`를 먼저 찾고 기존 AppData 개발 환경도 지원합니다.

**`build.cmd`를 더블클릭하면** 버전별 Windows 배포 폴더와 ZIP을 만듭니다. 결과는 빌드 저장소 아래 `AutoLog-<SW버전>_<날짜_시각>/`에 저장하며 같은 버전을 다시 빌드해도 기존 파일을 덮어쓰지 않습니다. `AutoLog.exe`와 `_internal/`을 포함한 폴더 전체 또는 생성한 ZIP을 배포합니다.

프로젝트가 사용자 `Documents` 안에 있는 이 PC의 기본 빌드 저장소는 `%USERPROFILE%\Downloads\AutoLog_Builds\`입니다. 그 외 경로에서는 프로젝트 `outputs/`를 사용하며 쓰기가 보호된 경우 다운로드 위치를 사용합니다. 실제 저장 경로는 빌드 화면에 표시하며 보안 설정은 변경하지 않습니다.

SW 버전은 `src/vil_logging/__init__.py`의 `__version__` 한 곳에서 바꿉니다. 앱, 패키지, EXE 속성, 빌드 폴더명이 이 값을 함께 사용합니다. 빌드 상세 정보와 오류는 결과 폴더의 `build_info.json`과 `build.log`에 있습니다.

## 실제 기록과 개발자로그

차량 캡처 파일은 앱에서 사용자가 선택한 저장 위치에 저장합니다. 저장 폴더, CANoe 구성 경로, TShark 경로, NIC와 파일 형식은 앱이 기억합니다. 사용자 설정·번호·이력 DB는 `%LOCALAPPDATA%\AutoLog`에 보관합니다.

개발자로그는 항상 기록하며, 소스 실행 시 저장소 루트의 `developer_logs/`, 배포 실행 시 EXE 옆 `developer_logs/`에 저장합니다. 기본 파일명은 `AutoLog_developer.jsonl`이며 5MB 파일 하나와 최대 4개 순환 백업으로 크기를 제한합니다.

**버그리포트** 버튼은 최근 로그와 백업을 ZIP으로 묶어 바탕화면에 저장하고 `Taegon.Kim`에게 해당 파일을 이메일로 보내 달라고 안내합니다. 앱이 이메일을 직접 보내지는 않습니다. 최근 활동 화면은 최대 500개를 표시합니다.

## 기존 사용자 데이터

이전 `%LOCALAPPDATA%\Auto_Log` 또는 `%LOCALAPPDATA%\VILLogging`의 SQLite 설정과 번호 이력은 새 프로필이 없을 때 `%LOCALAPPDATA%\AutoLog`로 복사합니다. 이전 기본 prefix는 `AutoLog`로 바꾸고 사용자 지정 prefix, 저장 경로, 장치 선택과 다음 번호는 유지합니다. 기존 캡처 파일은 이동하거나 이름을 바꾸지 않습니다. TShark 검색은 이전 도구 폴더도 지원합니다.

## 구현 및 검증 범위

기본 앱, 설정·번호·파일 이력, 진단 로그, 파일 관리와 TShark 기반 Ethernet 취득이 구현되어 있습니다. 0.5.1의 CANoe 독립 연결·출력 옵션 복구에 이어 0.6.0에서 미완료 캡처와 중단된 파일 작업의 수동 복구 화면을 추가했습니다. **대표 .cfg로 실제 CANoe 구간 기록을 검증하기 전인 시험용 버전**입니다. 차량 통신 판정과 고속·장시간·대용량 검증도 남아 있습니다. 모의 실행은 실제 BLF/PCAP를 만들지 않습니다.

기존 개발 기록에는 TShark/Npcap 설치 및 localhost 캡처 검증이 남아 있습니다. 이를 실제 차량의 취득 성능이나 모든 패킷의 무손실 저장을 검증한 결과로 해석하지 않습니다. 공통 시작 버튼도 두 도구의 정확한 동시 취득이나 시간 동기화를 보장하지 않습니다.

## 개발과 문서

새 PC의 도구 설치와 재확인은 [시험 PC 준비 안내](docs/test_pc_setup.md#새-pc에서-시작하기)를 따릅니다.

현재 구현 현황과 남은 작업은 [구현 계획](docs/implementation_plan.md)의 5절·10절에서 확인합니다.

코드, 검사, 문서, 의존성 정의와 빌드 사양을 함께 커밋합니다. 빌드 결과, 실제 캡처·진단 로그, PC별 설정과 원본 `.cfg`는 제외합니다. 원격은 `https://github.com/tgkim3245/AutoLog.git`입니다.

```powershell
git status --short --branch
git ls-files src
```

- [개발·Git 작업 안내](CONTRIBUTING.md)
- [현재 프로젝트 구조](docs/project_structure.md)
- [요구사항](docs/requirements.md), [설계](docs/architecture.md), [제어 정책](docs/control_policy.md)
- [초기 구현 검토 — 과거 기록](docs/requirements_implementation_review.md), [검증 계획](docs/validation_plan.md)
- [시험 PC 준비 항목](docs/test_pc_setup.md), [사용자 가이드](user_guide/user_guide_draft.md)
- [개발 이력](docs/development_log.md), [로컬 산출물 안내](outputs/README.md)
