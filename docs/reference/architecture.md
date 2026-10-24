# 현재 구현 구조

기준 SW 0.9.21 · 코드 대조 2026-10-25

Windows 11 x64의 Python 3.14·PySide6 데스크톱 앱이다. 메인 UI는 명령을 요청하고 제한된 알림을 소비하며, COM·파일 작업·worker 응답 대기는 별도 실행 문맥에서 수행한다. 내부 패키지명 `vil_logging`과 이전 데이터 이행 호환 이름은 제품 표시명과 구분한다.

## 실행과 책임

| 경로 | 현재 역할 |
| --- | --- |
| `src/vil_logging/app.py` | CLI·프로필/단일 실행·상시 진단·UI/Runtime 연결·이벤트 루프·X guard |
| `src/vil_logging/runtime.py` | 단일 coordinator executor에서 DB·세션·worker 파이프·보관·재실행 정리 조정 |
| `ui/` | 메인·설정·유효성검사·복구·읽기 전용 작업 이력·상태별 버튼·세 언어 |
| `contracts/` | 역할·상태·설정·세션 계획·명령/결과·이벤트 자료형 |
| `workers/` | 역할별 프로세스·명령 ID/진행/응답·소유 도구와 CANoe 핸들·유한 요약 큐 |
| `adapters/` | CANoe COM 블록 제어, dumpcap 원본 취득, TShark 후행 해석 |
| `monitors/` | Ethernet 수신 규칙·시간/지속 기준·관측 유효성과 위반 유지 |
| `storage/` | SQLite·예약 번호·이행·파일 식별/보관·BLF 완결·중단 폐기·아카이브 |
| `diagnostics/` | 도구/COM/채널/NIC 준비·상시 JSONL·수신/품질·UI 지연·명시적 부하 검사 |
| `documentation.py` | 배포/소스 공통 가이드 렌더·번역/사진/좌표/버전 검증 |
| `verification.py` | 생성 파일·localhost를 사용하는 명시적 CLI 검증 |
| `packaging/` | 버전별 PyInstaller 빌드·Wireshark/Npcap 고정 자료·배포 무결성 |
| `tools/` | TC 문서 생성과 문서 링크/생성물 최신성 검사. 앱 런타임에 포함하지 않음 |

`FakeWorkerPool`은 demo뿐 아니라 실제 pool의 공통 요청/응답 기반도 제공한다. 모의 worker·PacketBridge·복구·오프라인 검증 코드는 테스트와 실제 오류/호환 경로에서 참조하므로 화면에 보이지 않는다는 이유로 제거하지 않는다.

## UI와 실행 문맥

UI는 시작·정지·연결·설정·파일 작업을 Runtime에 제출한다. Runtime의 단일 coordinator가 SQLite와 worker 파이프 소유권을 유지한다. 도구/연결 진단은 별도의 제한된 executor를 사용하고 결과는 역할별 세대로 확인한다. 오래된 결과가 바뀐 설정을 덮어쓰지 않도록 한다.

기본 메시지 큐는 512개, 원래 패킷 전송 큐는 1000개, 진단 큐는 4096개로 제한된다. 일반 캡처는 화면 패킷 IPC를 끄며 최근 패킷 보기 창은 없다. 명시적 검증 경로의 요약 전달과 원본 캡처 누락 통계는 별개다. 메인 최근 활동은 500건을 유지한다.

## CAN과 Diag

각 역할에 다른 cfg와 하나의 BLF 블록을 연결한다. 독립 COM 활성화는 guard로 직렬화하며 필요한 `SingleCOMClient=1`을 원본 can.ini 백업과 함께 준비한다. 이미 공유 모드 CANoe가 있으면 작업 저장·종료 후 재연결을 안내한다. COM 등록 누락/손상은 공식 RegisterComponents 경로를 안내하되 레지스트리를 자동 수정하거나 다른 버전을 임의 선택하지 않는다.

사용자가 F9·Trace와 라이선스/컴파일·채널을 확인한다. 앱은 원본 cfg·CAPL을 자동 저장/재로드하지 않고 이번 구간의 출력 경로·옵션만 관리한다. 선택 블록을 정지한 뒤 측정을 유지한 채 BLF를 완결한다. 안정된 완전 복사본 보관과 원본 핸들 지연 해제를 구분한다.

## Zipy

선택한 NIC 하나에서 dumpcap이 PCAP/PCAPNG 원본을 직접 기록하고 별도 TShark가 증가 중인 파일을 후행 해석한다. 해석 실패는 원본 취득 경로와 구분해 관측 확인 불가로 처리하며 지속되면 정책에 따라 전체 기록을 정지한다.

동봉 도구가 기본이며 직접 선택한 설치본도 사용할 수 있다. Npcap 드라이버는 대상 PC 준비 조건이다. 캡처 버퍼는 64 MiB 고정이며 파일 크기 상한이 아니다. 유효성 규칙은 원본 필터가 아니며 다른 Source도 저장한다.

## 세션과 파일

`idle → preparing → starting → recording → stopping → completed`가 정상 흐름이다. 부분 오류는 partial, 실패는 failed, 현재 정지·보관 확인 필요는 incomplete로 구분한다. 화면 상태와 실제 파일별 보관 상태를 하나로 합치지 않는다.

준비·충돌 검사·CANoe 출력 적용 후 세션과 다음 번호를 영구 예약하고 기록한다. 시작 실패는 이번에 요청한 기록만 정리한다. 기록 중 오류는 전체 선택 기록을 정지한다. 메인 정지는 보관하며 X는 미완료 소유 구간을 폐기한다. 상세 상태와 제한은 [제어 정책](control_policy.md)을 따른다.

```text
선택 저장 폴더/
  .vil_work/세션UUID/          기록 중·마무리 소유 파일
  One_Click_Log_7.blf         CAN 완료 파일
  One_Click_Log_Diag_7.blf    Diag 완료 파일
  One_Click_Log_7.pcap        Zipy 완료 파일
```

## 저장물과 검증 경계

설정/번호/이력 DB는 `%LOCALAPPDATA%\One Click Log`, 진단은 실행 EXE 옆 `developer_logs`, 내보낸 ZIP은 바탕화면이다. 진단의 약 25 MiB 순환과 DB 아카이브는 캡처 보관과 별개다. [진단 안내](../guides/diagnostics.md)를 따른다.

모의 실행은 실제 캡처 파일을 만들지 않는다. 기본 자동 검사는 생성 자료·대역·테스트 프로세스로 수행하고 실제 cfg·물리 차량 NIC를 열지 않는다. 과거 현장 근거·알려진 누락·새 버전 재시험은 [현재 상태](implementation_status.md)에서 구분한다.
