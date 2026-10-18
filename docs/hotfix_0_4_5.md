# 0.4.5 — AutoLog 이름 정리

2026-10-18 · AutoLog 0.4.5

## 변경

- 제품명과 실행 파일을 `AutoLog` / `AutoLog.exe`로 통일한다. 기본 캡처 이름은 `AutoLog_1.blf`, `AutoLog_Diag_1.blf`, `AutoLog_1.pcap`이다.
- 새 사용자 데이터는 `%LOCALAPPDATA%\AutoLog`에 보관한다. 이전 `%LOCALAPPDATA%\Auto_Log`와 `%LOCALAPPDATA%\VILLogging` 중 먼저 있는 프로필을 SQLite 백업 API로 한 번 복사한다. 기본 prefix `Auto_Log`와 `VIL`은 `AutoLog`로 바꾸며 사용자 설정, 저장 경로, 인덱스와 기존 캡처는 유지한다.
- 개발자로그와 버그리포트 파일명은 `AutoLog_developer.jsonl`, `AutoLog_BugReport_YYYYMMDD_HHMMSS.zip`으로 바꾼다.
- 이전 프로그램이 실행 중이면 설정 이관을 멈추고 종료 안내를 표시한다. TShark와 Npcap 탐색은 이전 `Auto_Log` 및 `VILLogging` 도구 경로도 확인한다.
- Python 패키지 내부의 `vil_logging` 모듈 경로는 내부 호환성을 위해 유지한다. 콘솔 명령은 `autolog`을 추가하고 `auto-log` 별칭도 계속 제공한다.

## Git 및 산출물

- 저장소에는 소스, 테스트, 라이선스와 사람이 관리하는 문서를 포함한다.
- 실행 파일, 설치 프로그램, 캡처, 개발 로그, 화면 캡처와 검증 산출물은 `outputs/` 아래 로컬에 두고 Git에는 커밋하지 않는다.
- 이 변경은 소스와 패키징 설정을 갱신한다. `AutoLog.exe`의 새 배포 빌드는 아직 생성하지 않았다.
