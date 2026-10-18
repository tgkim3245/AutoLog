# 0.4.5 — AutoLog 이름 정리와 자동 빌드

2026-10-18 · AutoLog 0.4.5

## 변경

- 제품명과 실행 파일을 `AutoLog` / `AutoLog.exe`로 통일한다. 기본 캡처 이름은 `AutoLog_1.blf`, `AutoLog_Diag_1.blf`, `AutoLog_1.pcap`이다.
- 새 사용자 데이터는 `%LOCALAPPDATA%\AutoLog`에 보관한다. 이전 `%LOCALAPPDATA%\Auto_Log`와 `%LOCALAPPDATA%\VILLogging` 중 먼저 있는 프로필을 SQLite 백업 API로 한 번 복사한다. 기본 prefix `Auto_Log`와 `VIL`은 `AutoLog`로 바꾸며 사용자 설정, 저장 경로, 인덱스와 기존 캡처는 유지한다.
- 개발자로그와 버그리포트 파일명은 `AutoLog_developer.jsonl`, `AutoLog_BugReport_YYYYMMDD_HHMMSS.zip`으로 바꾼다.
- 이전 프로그램이 실행 중이면 설정 이관을 멈추고 종료 안내를 표시한다. TShark와 Npcap 탐색은 이전 `Auto_Log` 및 `VILLogging` 도구 경로도 확인한다.
- Python 패키지 내부의 `vil_logging` 모듈 경로는 내부 호환성을 위해 유지한다. 콘솔 명령은 `autolog`을 추가하고 `auto-log` 별칭도 계속 제공한다.
- 루트 `build.cmd`로 버전·시각이 표시된 배포 폴더와 ZIP을 자동 생성한다. SW 버전은 `src/vil_logging/__init__.py` 한 곳에서 관리하며 패키지 버전, EXE 속성과 출력 폴더명도 같은 값을 사용한다.

## Git 및 산출물

- 저장소에는 소스, 테스트, 라이선스와 사람이 관리하는 문서를 포함한다.
- 빌드 산출물은 프로젝트 `outputs/` 또는 Documents 쓰기 보호가 있는 PC의 `Downloads/AutoLog_Builds/`에 보관하고 Git에는 포함하지 않는다. 실제 캡처는 앱에서 선택한 폴더에 저장한다.
- 이 PC에서는 Windows Defender의 Documents 쓰기 차단을 확인하여 보안 설정 변경 없이 다운로드 위치에 새 배포본을 만들었다. [자동 빌드 안내](../CONTRIBUTING.md#빌드)를 따른다.

## 2026-10-18 빌드 검증

- 소스 커밋 `49eda3f`, 빌드명 `AutoLog-0.4.5_20261018_131648`. 미커밋 소스 변경이 없는 상태에서 생성했다.
- EXE 속성의 제품명 AutoLog, 파일·제품 버전 0.4.5를 확인했다. ZIP 무결성과 EXE·ZIP SHA-256이 빌드 정보와 일치했다.
- ZIP을 별도 폴더에 풀고 Python 개발 경로를 제거한 환경에서 모의 기록·정지·정상 종료를 확인했다. 종료 코드 0, 상시 진단 로그 55건과 필수 완료 이벤트를 확인했다.
- 상세 결과는 해당 빌드 폴더의 `verification/result.json`에 있다. 실제 시험 PC의 차량 NIC, CANoe 구성과 고속·장시간 취득은 별도 검증 항목이다.
