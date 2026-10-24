# 0.4.4 — Auto_Log 이름 및 파일 규칙

> 과거 기록: 이 문서는 작성 당시의 변경·검증 근거를 보존합니다. 현재 동작과 남은 확인 사항은 [현재 구현 상태](../reference/implementation_status.md)를 따릅니다.

2026-10-18 · Auto_Log 0.4.4

실행 파일: `%USERPROFILE%\Downloads\Auto_Log-0.4.4\Auto_Log\Auto_Log.exe`. 실행 폴더의 `_internal` 디렉터리와 함께 유지합니다. ZIP 배포본은 같은 상위 폴더의 `Auto_Log-0.4.4.zip`입니다.

## 변경

- 앱 제목, 빌드 산출물, 기본 캡처 prefix, 진단 로그와 버그리포트 파일명을 `Auto_Log`로 맞췄습니다. 새 설치 캡처 예: `Auto_Log_1.blf`, `Auto_Log_Diag_1.blf`, `Auto_Log_1.pcap`.
- 버그리포트 팝업에서 이메일 주소를 제거하고 `Taegon.Kim`에게 이메일로 보내 달라는 문구만 표시합니다. ZIP 파일명은 `Auto_Log_BugReport_YYYYMMDD_HHMMSS.zip`입니다.
- 상시 진단 로그는 배포 폴더 내부 `developer_logs\Auto_Log_developer.jsonl`에 5MB 단위로 저장하고 최대 4개 백업을 보관합니다.
- 기존 `%LOCALAPPDATA%\VILLogging` 프로필은 새 프로필이 없을 때만 SQLite 백업 API로 이관합니다. 기본 `VIL` prefix만 `Auto_Log`로 바꾸고 저장 위치, 인덱스와 사용자 지정 prefix를 유지합니다. 기존 데이터는 삭제하지 않습니다. TShark 자동 검색은 새 위치를 먼저 확인하고 기존 도구 폴더도 계속 검색합니다.
- 기존 VIL Logging이 실행 중이면 종료 후 다시 실행하라는 안내를 표시합니다. 새 버전을 실행했는데 구버전 화면이 조용히 활성화되던 동작을 없앴습니다.

## 검증

- 자동 테스트 211개와 Ruff 검사를 통과했습니다. 테스트 캐시는 문서 폴더 보호로 저장하지 못했지만 테스트 결과는 통과했습니다.
- Python 3.14.7 / PyInstaller 6.22.3으로 폴더형 배포본을 빌드했습니다. Windows 제어된 폴더 액세스의 문서 폴더 쓰기 차단(이벤트 1123)을 확인해 다운로드 폴더에 생성했습니다. Defender 설정은 변경하지 않았습니다.
- 새 배포 폴더를 Microsoft Defender로 직접 검사해 위협 없음과 종료 코드 0을 확인했습니다. 이는 이번 검사 결과이며 서명이나 모든 PC에서의 탐지 면제를 의미하지 않습니다.
- 배포 EXE의 모의 기록 시작·정지, 상시 개발자로그와 TShark/NIC 자동 탐색을 종료 코드 0으로 검증했습니다. 개발자로그가 실행 파일 옆 `developer_logs`에 생성되는 것도 확인했습니다.
- 배포 EXE에서 localhost UDP만 사용해 PCAP/PCAPNG 각각 빈 캡처·5패킷 캡처·재시작 총 6건을 검증했습니다. 오프라인 ARP 요약도 통과했습니다. 실제 차량 NIC는 열지 않았습니다.
- 배포 EXE에서 생성한 PCAP 파일의 이름 변경, 재실행 후 경로 유지, 사용 중 파일 보호, 삭제와 번호 유지를 검증했습니다.
- 배포 폴더의 `build_info.json`과 상위 `validation` 폴더에 검사 결과를 보관합니다. 시험 PC의 실제 CANoe 구성, 차량 NIC, 고속·장시간 캡처는 별도 확인 항목입니다.
