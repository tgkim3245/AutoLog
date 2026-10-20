# AutoLog

Windows용 CANoe/Wireshark 로깅 제어 앱입니다. CAN, Diag, Zipy 대상을 선택하고 공통 logging 버튼으로 기록을 제어합니다.

배포받은 사용자는 EXE 옆 **START_HERE.txt**와 **AutoLog_User_Guide.html**을 먼저 읽으세요. Defender의 `CAPLcompExec.exe`·`CANoe64.exe` 허용 앱 등록과 최초 연결·기록·복구 절차를 안내합니다. [공식 사용자 가이드 관리 원본·변경 이력](user_guide/README.md)은 소프트웨어 변경과 함께 갱신하며 빌드/ZIP에 자동 포함합니다.

현재 소스 버전은 **0.9.3**입니다. [수동 기록 후 파일명 변경 차단 수정](docs/canoe_fixes_0_9_3.md), 이전 [CANoe 기록 시작 오류 수정](docs/canoe_fixes_0_9_2.md), [준비 오류 수정](docs/canoe_fixes_0_9_1.md), [사용성·채널 확인·캡처 분리 변경](docs/usability_update_0_9_0.md), [CANoe 환경별 검증표](docs/canoe_support_matrix.md)를 확인하세요. CAN과 Diag의 **연결 확인**은 각 .cfg를 별도 CANoe 창에 연결하고 구성 열기·측정 대기·구간 기록 준비를 구분합니다. 로컬 Vector 장치의 채널을 조회할 수 있으면 시리얼·포트를 기준으로 저장해 다음 연결/시작 때 비교합니다. 조회 불가와 실제 수신 성공은 구분합니다. 이전 [전체 검토](docs/project_audit_0_8_6.md), [개선 항목별 상태](docs/improvement_backlog.md), [개발 안내](CONTRIBUTING.md)도 참고하세요.

**기록 품질**에서 파일 크기·증가 속도·해석 속도/지연·표시 큐 누락·저장 공간을 확인합니다. 종료 파일이 제공하는 원본 누락 통계와 화면 누락은 구분하며, 통계가 없으면 확인 불가로 표시합니다. 캡처 버퍼는 **64 MiB 고정**이며 최대 파일 크기를 제한하지 않습니다. 번호를 넣은 localhost 반복 시험은 `--verify-load`로 실행할 수 있습니다.

기본 선택은 **CAN·Zipy**입니다. `한 | EN | 中` 버튼은 클릭할 때마다 표시 언어를 바꾸고 기억합니다. Ethernet 설정에서 `tshark.exe`를 직접 지정하며, 네트워크 목록 오른쪽 그래프는 해당 어댑터 전체의 초당 수신 패킷 수입니다. **로그 폴더**는 사용자가 지정한 캡처 저장 폴더를 엽니다.

dumpcap이 원본 파일을 직접 기록하고 TShark는 저장 중인 파일을 읽어 화면·감시용 정보를 만듭니다. 해석이 중단되면 감시는 확인 불가로 표시하며 원본 기록은 유지합니다. 메인 창은 화면 높이에 맞춰 스크롤할 수 있고 최근 활동은 전체/경고·오류/오류로 걸러 선택한 항목의 상세를 복사할 수 있습니다.

**통신 감시 → 감시 기준**에서 Zipy의 목적지·프로토콜·기대 출처와 시간/복귀 기준을 직접 저장하면 다음 기록부터 감시합니다. 기준값은 기본으로 비어 있으며, 미수신·다른 출처·복귀·관측 지연을 구분합니다. 패킷 표시 필터·일시 정지·화면 큐 누락과 감시는 독립적이며, 경고로 기록을 자동 정지하지 않습니다. CAN·Diag의 실제 수신 감시는 현재 미지원입니다.

비정상 종료 후에는 메인의 **미완료 확인 N건** 또는 **파일 관리 → 미완료 기록 복구**에서 파일을 검토합니다. 외부 기록 종료를 직접 확인한 뒤 **검사 후 보관**하거나 **파일 유지하고 미완료 정리**할 수 있습니다. 파일과 소비한 번호를 유지하며 복구 세션은 실패 이력으로 남깁니다.

CAN과 Diag는 각각 하나의 .cfg와 그 안의 BLF 기록 블록 하나를 사용합니다. AutoLog가 첫 연결에서 필요한 CANoe 독립 COM 모드를 자동 준비하며, 원본 can.ini는 같은 폴더에 백업합니다. 이미 기본 COM 모드로 실행된 CANoe가 있으면 최초 한 번 작업을 저장하고 모든 CANoe 창을 닫은 뒤 연결 확인을 다시 누르세요. 이후 두 구성은 자동으로 각각 열립니다. 설정은 해당 CANoe 설치 전체에 유지되며 다른 COM 도구·ActiveX/.NET 패널도 영향을 받을 수 있습니다. 대표 구성과 실제 버튼 경로의 두 프로세스·정확한 cfg 연결을 CANoe 19.3.118에서 확인했습니다. 0.9.0 현장 시도에서도 서로 다른 PID의 연결을 확인했으나 실제 기록 준비에서 차단됐습니다. 사용자가 CANoe에서 확인한 `Ethernet (missing)`은 선택한 cfg가 요구하는 버스 옵션 문제이며 채널 매핑과 별도로 확인해야 합니다. 실제 BLF 구간 기록 성공은 아직 검증하지 못했습니다.

AutoLog로 cfg를 연 뒤 해당 CANoe 창에서 채널 매핑과 cfg에 필요한 모든 버스 옵션의 라이선스를 확인하고 **F9 측정 실행 → Trace 수신 확인 → AutoLog 연결 확인** 순서로 준비하세요. 측정 실패 시 CANoe Write 창의 오류를 확인합니다. BLF 블록만 선택하거나 AutoLog의 Zipy를 해제해도 cfg의 Ethernet 요구 사항이 없어지지는 않습니다. 원본 cfg와 라이선스 설정은 AutoLog가 변경하지 않습니다.

대표 cfg의 `Logging` 패널 버튼은 CAPL에서 로깅을 제어하는 별도 버튼입니다. AutoLog는 패널을 클릭하거나 시스템 변수를 바꾸지 않고 선택한 `CAN_Logging` 같은 BLF 블록을 직접 제어합니다. 패널 색으로 AutoLog의 기록 상태를 판단하거나 두 제어를 함께 사용하지 마세요. 0.9.1 현장 로그에서 측정 실행과 BLF 블록 선택은 확인됐지만 출력 적용 직후 COM 객체 비교가 실패했습니다. 0.9.2는 전체 구간에서 논리 블록과 소유 출력 경로를 검증하며 조회 객체 주소에 의존하지 않습니다. 새 버전의 실제 장비 구간 기록 재시험은 남아 있습니다.

0.9.2의 다음 현장 시도에서는 수동 시험 후 바뀐 BLF 파일명을 다른 블록으로 오인해 시작 전에 차단했습니다. 0.9.3은 수동 기록을 멈춘 뒤 같은 cfg·유일한 이름의 블록에서 BLF 파일명만 바뀌면 재연결 없이 받아들입니다. AutoLog가 출력 경로를 적용한 뒤에는 외부 경로 변경을 계속 차단하며 정리 후에는 시작 직전의 경로·옵션으로 복구합니다. CAN·Diag 수동 성공은 사용자 확인이고 새 AutoLog 버전의 실제 자동 기록 성공은 아직 확인하지 못했습니다.

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

배포 문서는 SW 버전과 별도로 개정을 관리합니다. 가이드의 검토 버전이 현재 SW와 다르거나 문서 원본이 누락되면 빌드를 중단합니다. `build_info.json`에는 문서 개정·갱신일·두 문서의 크기와 SHA256도 기록합니다.

## 실제 기록과 개발자로그

차량 캡처 파일은 앱에서 사용자가 선택한 저장 위치에 저장합니다. 저장 폴더, CANoe 구성 경로, TShark 경로, NIC와 파일 형식은 앱이 기억합니다. 사용자 설정·번호·이력 DB는 `%LOCALAPPDATA%\AutoLog`에 보관합니다.

시작할 때 오래된 DB 이력을 같은 프로필의 `history_archive/AutoLog_history_*.jsonl.gz`로 내보내고 재읽기·해시 확인 후 정리합니다. 기본 90일·이벤트 10,000개·완료 세션/완료 파일 작업 각 1,000개 기준이며 최근 이벤트 500개와 완료 이력 각 100개는 남깁니다. 미완료·실패·미확인 파일 작업 관련 이력은 보존하고 캡처 파일과 다음 번호는 변경하지 않습니다. 내보내기 실패 시 DB도 유지합니다.

개발자로그는 항상 기록하며, 소스 실행 시 저장소 루트의 `developer_logs/`, 배포 실행 시 EXE 옆 `developer_logs/`에 저장합니다. 기본 파일명은 `AutoLog_developer.jsonl`이며 5MB 파일 하나와 최대 4개 순환 백업으로 크기를 제한합니다.

**버그리포트** 버튼은 최근 로그와 백업을 ZIP으로 묶어 바탕화면에 저장하고 `Taegon.Kim`에게 해당 파일을 이메일로 보내 달라고 안내합니다. ZIP의 `manifest.json`에 원본별 크기와 SHA256을 넣고 저장 전에 검증합니다. 압축 크기와 원본 크기는 다르며 내보낸 뒤에도 원본 로그는 계속 증가합니다. 앱이 이메일을 직접 보내지는 않습니다. 최근 활동 화면은 최대 500개를 표시합니다.

## 기존 사용자 데이터

이전 `%LOCALAPPDATA%\Auto_Log` 또는 `%LOCALAPPDATA%\VILLogging`의 SQLite 설정과 번호 이력은 새 프로필이 없을 때 `%LOCALAPPDATA%\AutoLog`로 복사합니다. 이전 기본 prefix는 `AutoLog`로 바꾸고 사용자 지정 prefix, 저장 경로, 장치 선택과 다음 번호는 유지합니다. 기존 캡처 파일은 이동하거나 이름을 바꾸지 않습니다. 이전에 선택한 TShark 경로도 유지하며 자동으로 다른 설치본으로 바꾸지 않습니다.

## 구현 및 검증 범위

기본 앱, 설정·번호·파일 이력, 진단 로그, 파일 관리와 TShark 기반 Ethernet 취득이 구현되어 있습니다. 0.6.0의 수동 복구, 0.7.0의 Ethernet 감시에 이어 0.8.0에서 기록 품질 계측과 번호 기반 부하 검사를 추가했습니다. **대표 .cfg로 실제 CANoe 구간 기록을 검증하기 전인 시험용 버전**입니다. 60초 localhost 시험과 실제 차량 조건의 고속·장시간·대용량 지원은 구분합니다. 실제 차량의 감시 기준·채널/수신 관측 지원도 남아 있습니다. 모의 실행은 실제 BLF/PCAP를 만들지 않습니다.

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
- [시험 PC 준비 항목](docs/test_pc_setup.md), [공식 사용자 가이드](user_guide/README.md)
- [개발 이력](docs/development_log.md), [로컬 산출물 안내](outputs/README.md)
