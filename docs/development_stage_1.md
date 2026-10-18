# 1단계 개발 결과와 실행 방법

기준일: 2026-10-17 (Asia/Seoul)
버전: 0.1.0 개발 빌드
범위: 개발 환경, 기본 앱·개발자로그, 저장·상태·모의 작업 프로세스. 실제 도구 연동은 다음 기술 실증 단계다.

## 실행

프로젝트 루트의 `run_demo.cmd`를 실행하면 실제 도구나 NIC를 열지 않는 모의 앱을 사용할 수 있다. `logging`으로 모의 시작·정지를 확인하고, 상단의 작은 **개발자로그** 체크박스를 켜서 진단 파일 저장을 시험한다. 모의 실행에서는 BLF/PCAP/PCAPNG를 만들지 않는다. 표시되는 캡처 파일명은 계획이며 화면에 파일 미생성을 명시한다.

`run.cmd`는 기본 앱을 연다. 기본 앱은 설정·환경 확인·개발자로그를 사용할 수 있고 실제 연결·기록은 아직 시작하지 않는다. 실제 연동 미지원 상태에서 연결 성공을 표시하거나 번호를 소비하지 않는다.

빌드 결과는 `outputs/stage1/VILLogging/` 폴더로 제공한다. 그 안의 `VILLogging.exe`가 기본 앱이고 `모의실행.cmd`가 모의 앱을 연다. EXE와 `_internal` 등을 포함한 폴더 전체를 유지한다. 현재 개발 PC에서 검증하는 초기 빌드이며 실제 시험 PC·Python 없는 새 PC에서의 운용 검증은 남아 있다.

창의 X는 트레이 숨김이다. 종료하려면 설정 또는 트레이의 **프로그램 종료**를 사용한다. 모의 기록 정지와 상태 저장을 확인한 뒤 앱을 끝낸다.

## 개발자로그 사용

1. 문제를 재현하기 전에 상단 **개발자로그**를 체크한다. 매 실행 기본값은 해제이며 이전의 ON 상태를 기억하지 않는다.
2. 설정·연결 준비·logging 등 필요한 동작을 수행한다.
3. 체크를 해제하면 대기 중인 진단을 기록하고 파일을 닫는다. 일반 동작 이력과 번호 DB는 이 체크와 독립적으로 유지한다.
4. **로그 폴더** 버튼에서 파일을 찾는다. 문제가 발생한 실행의 `.jsonl` 파일과 같은 이름의 `.1`~`.4` 회전 파일이 있으면 함께 전달할 수 있다. 자동 전송은 하지 않는다.

기본 앱의 위치는 `%LOCALAPPDATA%\VILLogging\developer_logs\`, 모의 앱은 `%LOCALAPPDATA%\VILLogging\demo\developer_logs\`다. `--data-dir`를 지정한 개발/검사 실행에서는 해당 폴더 아래에 생긴다. 한 번도 활성화하지 않으면 개발자로그 파일이나 폴더를 만들지 않는다.

진단은 UTF-8 JSONL(한 줄에 JSON 한 건)이다. UTC 시각·단조 시계·앱/Python/OS 버전·프로세스/스레드·이벤트·대상·세션/명령 ID·상태·처리 시간·실제 경로·오류 원문·traceback을 저장한다. 작업 프로세스의 명령 내부 및 명령 사이 예외도 부모 진단으로 회수한다. 원본 패킷 바이트와 차량 데이터 payload는 자동 기록하지 않는다.

활성화 한 번마다 새 파일을 만들고 기본 5MiB 단위로 최대 5개 파일을 사용한다. 과거 실행의 파일은 자동으로 삭제하지 않는다. 화면과 제어를 기다리게 하지 않는 유한 비동기 큐를 사용한다. 파일 쓰기 실패·큐 누락은 화면과 상태로 알리며 진단 실패만으로 기록 제어를 중단하지 않는다.

## 이번 단계에서 구현한 내용

| 영역 | 현재 제공 |
| --- | --- |
| 개발 기반 | Python 패키지·프로젝트 정의·의존성 고정·로컬 Git 저장소 초기화·실행 스크립트 |
| 화면 | 약 480px 메인, CAN/Diag/Zipy 선택, 설정, 한국어/영어, 상단 개발자로그, 최근 이력 200건, 패킷 창 1,000건, 트레이 |
| 저장 | 사용자별 SQLite, 설정 버전, 큰 정수 번호의 정확한 예약·증가, 파일 계획, 이벤트, 미완료 세션 회수 |
| 모의 제어 | 대상별 별도 프로세스, 명시적 Prepare/Start/Stop/Query, 명령/세션 ID, 시작 취소, 늦은 응답, 시작 실패 정리, 도중 부분 실패와 다른 대상 유지 |
| 진단 | 선택적 JSONL·회전·예외 근거, 로컬 환경/도구 파일·버전·COM 등록 확인. CANoe 객체 생성·측정·NIC 캡처는 수행하지 않음 |
| 패키징 | PyInstaller Windows x64 폴더 빌드와 기본 앱/모의 프로세스의 자체 확인 경로 |

파일 보관·직전 이름 변경·삭제·작업 도중 복구, 실제 CANoe/TShark 어댑터, 실제 통신 감시, 장시간/대용량·다른 PC 검증은 후속 단계다. 해당 파일 관리 버튼은 현재 비활성화한다. 미완료 세션의 자동 성공 처리·번호 재사용·이전 CANoe 자동 연결도 하지 않는다. 수동 복구 UI는 후속 단계에서 연결한다.

## 검증

자동 검사는 실제 장비를 열지 않는다. 테스트별 검증 범위는 `tests/unit`과 `tests/integration`에 있으며 최종 실행 결과는 [개발 기록](development_log.md)에 남긴다.

최종 결과: 자동 검사 93개·Ruff·의존성 검사 통과. 폴더 EXE도 현재 개발 PC에서 Python 관련 경로를 제거한 조건으로 기본 OFF와 명시적 체크박스 ON/OFF 모의 실행·정상 종료를 확인했다. Python 없는 새 PC 검증은 별도다.

- 로그 기본 OFF, ON/OFF·flush·회전·Unicode·원문/traceback·파일/큐 오류.
- 큰 번호·이름 규칙·기존 파일 충돌·예약 실패 rollback·설정 버전·재실행·미완료 회수.
- UI 기본값·언어·미완료 잠금·대상 선택 독립성·유한 패킷/이력 표시.
- 시작/정지, 시작 실패 정리, 도중 일부 중단, 마지막 DB 저장 중 시작 취소, 한 프로세스 사망 후 다른 대상 정지, 늦은 응답·명령 사이 예외.
- 전체 앱의 시작→모의 기록→정지→정상 종료와 체크박스를 통한 실제 진단 파일 ON/OFF.

실제 CANoe 구성·장비·차량 NIC를 사용한 취득 시험은 아직 없다. 실제 기능의 완료 판정은 [구현 계획](implementation_plan.md)의 G-C1~C3/G-E/G-P를 따른다.

## 설치된 개발 환경

기존 Python 3.9는 유지했다. 공식 winget 카탈로그에서 제공하는 Python 3.14.7 일반 x64를 사용자 범위에 추가했다. 새 프로젝트 의존성은 `%LOCALAPPDATA%\VILLogging\development\venv314\` 가상환경에 설치했다. 정확한 패키지 버전은 [requirements.lock](../requirements.lock)에 기록한다.

현재 새 Python의 Documents 하위 폴더 생성/쓰기는 WinError 2로 실패하고 사용자 로컬 앱 데이터에서는 성공한다. 원인 보안 정책을 단정하거나 변경하지 않았다. 가상환경·검사 임시 파일·빌드 중간 결과는 사용자 로컬 앱 데이터에 두고, 소스는 현재 프로젝트에 유지한다. `run.cmd`는 프로젝트 `.venv`가 있으면 우선 사용하고 없으면 준비한 외부 가상환경을 사용한다.

일반 개발 PC에서는 해당 Python으로 `.venv`를 만들고 `requirements.lock`을 설치할 수 있다. 현재 PC에서 검사할 때는 아래처럼 실행한다.

```powershell
$developmentPython = Join-Path $env:LOCALAPPDATA 'VILLogging\development\venv314\Scripts\python.exe'
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
& $developmentPython -m pytest -p no:cacheprovider
& $developmentPython -m ruff check --no-cache src\vil_logging tests
& $developmentPython -m vil_logging --diagnose
```

`--diagnose`는 도구 존재·버전·COM 등록 등의 읽기 전용 확인 결과를 JSON으로 출력한다. 라이선스·실제 제어·물리 연결 성공을 판정하는 명령은 아니다. 현재 확인 범위에서 CANoe 설치/COM 등록은 발견했고 TShark/Npcap은 발견하지 못했다. 이번 단계에 필요하지 않은 드라이버나 기존 CANoe는 설치·변경하지 않았다.

다음은 대표 CAN/Diag `.cfg`와 시험 PC 조건을 확보해 CANoe 독립 제어·측정 유지 구간 기록을 검증하고, 실제 Ethernet 연동 단계에서 필요한 Wireshark 도구·Npcap을 준비하는 순서다.

사용자 확인: 대표 `.cfg` 경로는 시험 PC에서 나중에 확인한다. 현재 개발 PC에서 임의의 구성이나 기존 CANoe 창으로 대체 검증하지 않는다.
