# CANoe 19 · Wireshark 통합 패널 구현 가능성 검토

> 이 문서는 초기 논의와 제어 경로 검토 기록이다. 이후 사용자 답변과 보완을 반영한 현재 기준은 [요구사항](requirements.md)과 [제어 정책](control_policy.md)이다. 기록 도중 다른 대상 유지·통합 패킷 목록·로깅 중 감시는 후속 결정으로 확정됐다.

검토일: 2026-10-17 (Asia/Seoul)
역할: 설계 검토. 이 문서는 실행 코드나 실제 장비 검증 결과가 아니다.

## 0. 사용자 정정을 반영한 검토 기준

2026-10-17 추가 설명을 반영한다.

- CANoe는 번개 버튼으로 측정을 계속 유지하며, 기존 Logging 패널의 첫 버튼 입력부터 다음 입력까지의 구간을 이미 저장하고 있다. 이는 확인된 현행 동작이다. 검토 대상은 이 기능을 새로 만들 수 있는지가 아니라 기존 버튼이 제어하는 대상과 외부 제어 경로다.
- Wireshark는 기본 설정에서 캡처 중 패킷을 보여주고 임시 캡처 파일에 기록한다. 사용자는 캡처를 중지한 후 이름·경로를 정해 보관하거나, 보관하지 않고 새 캡처를 진행할 수 있다. 모든 패킷을 RAM에만 쌓다가 중지 후 처음 디스크에 쓰는 구조로 설명하지 않는다. [S15–S17]
- 'PCAP 정상 종료·저장'은 별도의 불확실한 제품 기능이 아니라 통합 패널이 수행해야 할 기본 동작이다. 캡처 중지와 최종 파일 보관은 개념상 나누되, 사용자 조작은 하나의 정지 버튼에서 함께 처리할 수 있다.
- Wireshark 자체 캡처 목록을 보는 데 별도 named pipe는 필요하지 않다. 앞서 제안한 증분 파일 읽기·named pipe는 캡처를 dumpcap으로 옮기는 경우의 대안이다. 이를 Wireshark 사용의 필수 조건으로 제시하지 않는다.
- 기존의 매회 별도 PCAP·BLF 파일 쌍 요구를 유지한다. 사용자가 설명한 Wireshark의 저장/미저장 선택은 현행 도구 동작 설명으로 받아들이며, 통합 패널에 저장 여부 선택 기능을 추가하라는 확정 요구로 해석하지 않는다.

## 1. 결론

**통합 제어는 구현 가능한 구조다. CANoe의 현행 구간 로깅과 Wireshark의 현행 캡처·표시·파일 저장을 기준으로, 별도 Windows 작은 창에서 각 기능을 제어하는 경로를 결정한다. CANoe는 COM 제어를 먼저 검토하고 CAPL은 기존 연결 또는 보조 기능에 필요한 경우 사용한다. Wireshark는 기존 GUI를 제어하는 안과 캡처 실행부를 별도로 두는 안을 비교한다.**

CANoe 19 공식 도움말에서 Logging 객체의 FullName 설명, Trigger 객체의 Start·Stop·Active, CAPL의 startLogging·stopLogging·closeLogFile을 직접 확인했다. Wireshark 공식 자료에서 dumpcap의 파일 기록과 Wireshark의 named pipe 실시간 입력을 확인했다. 따라서 단순히 화면 버튼을 대신 누르는 방식으로만 접근할 필요는 없다. [S1–S8]

실제 시험 PC에서 추가로 확인할 것은 CANoe 상세 빌드·프로젝트·로깅 제어 연결, Wireshark 외부 제어 수단, 통합 패널에서의 파일 대응·결과 확인이다. **공식 기능의 존재 확인과 현장 설정에서의 동작 검증은 구분한다.**

## 2. 이번 대화에서 확정·유보된 사항

| 항목 | 사용자 답변 | 설계에 반영할 내용 |
| --- | --- | --- |
| 패널 | CANoe 밖에서 실행하는 작은 창 | 별도 Windows 실행부가 두 도구를 제어한다. |
| 기존 CANoe 기록 | Logging 패널의 버튼으로 시작·정지를 토글 | 같은 Logging Block을 찾아 재사용하는 방식을 우선 확인한다. 기존 버튼이 CAPL인지 기본 기능인지는 미확정이다. |
| 파일 단위 | 시작 → 정지마다 별도의 PCAP·BLF 파일 쌍 | 일시 정지·재개와 파일 완결을 구분하고 새 구간마다 고유 파일을 만든다. |
| 사람의 패킷 확인 | 원하는 소스의 데이터가 들어오는지 직접 확인 필요 | Wireshark 실시간 창을 우선 검토하고, 필요하면 패널에 간단한 패킷 요약을 제공한다. |
| 자동 감시 | 원하는 소스의 수신 이상을 알려주길 원함 | 감시 경로는 설계하되 구체적인 판정은 기준 확정 후 구현한다. |
| 소스·주기 기준 | 추후 제공, 현재는 넘어감 | MAC/IP/프로토콜/포트/기대 주기/타임아웃을 임의로 정하지 않는다. 미설정은 정상으로 표시하지 않는다. |
| CANoe 프로젝트 수정 | CAPL·시스템 변수 추가 가능 여부 확인 필요 | 프로젝트 수정이 필수인 설계부터 확정하지 않는다. |
| 시험 환경 | 다른 시험 PC, CANoe 19, 다양한 CAN 장비, 미디어 컨버터를 통한 Ethernet | PC별 경로·장치·채널을 설정으로 분리하고 실제 시험 PC에서 검증한다. |

requirements.md와 화면 시안은 별도로 관리된다. 이 검토에는 사용자 답변과 외부 제어 경로 분석을 기록하며, 요구사항 파일과 화면 시안은 수정하지 않았다.

## 3. 구현 구성 제안

```text
작은 통합 패널
    ├─ CANoe 연결 담당
    │    └─ 현재 Logging 패널이 제어하는 기록 기능
    │         └─ COM 직접 제어 / 기존 변수 연결 / 필요 시 CAPL 보조
    └─ Wireshark 연결 담당
         ├─ 안 A: 기존 GUI 캡처·실시간 표시·중지·파일 저장을 제어
         └─ 안 B: 별도 캡처 도구가 취득하고, 관찰용 화면을 연결
```

안 A는 기존 작업 흐름을 그대로 재현하는 안이다. 안 B는 더 직접적으로 프로세스를 관리하는 대안이며 실시간 관찰 연결을 추가해야 한다. 사용자 작업이 이미 성립하는 상황에서 안 B의 내부 구조를 먼저 확정할 이유는 없다. 두 안의 외부 제어 수단과 안정성을 비교해 결정한다.

작은 창은 COM 접근과 Windows 프로세스·창 제어가 가능한 실행부를 사용한다. C# 또는 Python 등이 후보이며, 실제 도구 제어 경로가 정해진 뒤 유지보수·배포 환경에 맞춰 선택한다. [S1]

HTML 와이어프레임은 화면 시안이다. 실제 제어에는 Windows 실행부를 연결하거나 데스크톱 화면으로 옮겨야 한다.

## 4. CANoe: CAPL부터 작성하기 전에 확인할 경로

### 4.1 COM으로 기존 로깅 블록 직접 제어

CANoe 19 공식 도움말의 Logging 객체는 현재 구성의 Logging Block을 나타낸다. FullName의 확장 설명과 예제에는 경로 설정 및 BLF 파일 지정이 설명돼 있다. Trigger 객체에는 Start·Stop 메서드와 Active 속성이 명시돼 있다. [S2, S3]

개념적인 호출은 다음과 같다. 아래는 실행 코드가 아니라 이미 선택·검증한 객체에 대한 제어 순서다.

```text
대상 CANoe 인스턴스·프로젝트·Logging Block 확인
선택한 Logging Block의 현재 기록/트리거 상태 조회
허용되는 시점에 새 BLF 경로 또는 구간별 파일명 규칙 적용
selectedLogging.Trigger.Start()
트리거 응답·기록 증거 확인
...
selectedLogging.Trigger.Stop()
기록 구간 종료·파일 완결 확인
```

- 여러 로깅 블록 중 첫 번째 블록을 무조건 고르지 않는다. 기존 패널 버튼이 실제로 제어하는 블록을 확인한다.
- 기존 패널이 시스템 변수를 변경하는 사용자 정의 패널이라면, 해당 변수와 처리 코드를 재사용하는 대안도 있다. 이는 현재 프로젝트 확인 후 결정한다.
- 이미 시작된 측정을 유지하는 모드를 우선 검토한다. 전체 측정 Start/Stop을 기록 Start/Stop으로 대체하지 않는다.
- Trigger.Active는 트리거 상태에 대한 정보다. 파일에 정상 데이터가 쓰였고 닫혔다는 단독 증거로 사용하지 않는다.
- Logging.FullName 문서의 표에는 read-only 표기가 있지만 확장 설명·예제에는 setter가 제시된다. 실제 19 빌드에서 변경 가능 시점과 결과를 확인한다.

### 4.2 현행 구간 저장 동작을 외부에서 재현

사용자는 측정을 유지하면서 Logging 패널 버튼으로 구간별 데이터를 이미 저장하고 있다. 이 동작 자체를 미확인 사항으로 취급하거나 새로운 파일 닫힘 구조를 먼저 요구하지 않는다.

실제 연동에서 확인할 것은 다음과 같다.

1. 현재 버튼이 제어하는 Logging Block·트리거·시스템 변수 또는 CAPL 연결을 식별한다.
2. 외부 제어로 같은 대상에 기록 시작·정지를 전달한다.
3. 현재와 같은 구간·파일 생성 결과가 나오는지 비교한다.
4. 통합 패널에서 정한 PCAP·BLF 이름 및 파일 쌍 대응을 기존 파일명 설정과 연결한다.

CAPL의 stopLogging 이후 재개와 closeLogFile 이후 재시작은 서로 다른 동작이며, 파일 덮어쓰기 조건도 다르다. 이는 기존 동작의 가능성을 의심하는 근거가 아니라 새 코드를 작성할 때 기존 동작을 훼손하지 않기 위한 참고다. 기존 경로가 요구 동작을 충족하면 closeLogFile을 추가할 필요가 없다. [S5]

필요한 경우 트리거별 파일명 필드 `{IncTrigger|001}` 같은 기존 설정을 활용할 수 있다. 적용 여부는 현재 설정과 비교해 결정한다. [S6]

## 5. CAPL의 역할과 범위

| 기능 | CAPL 필요성에 대한 판단 |
| --- | --- |
| 외부 창에서 기존 Logging Block의 시작·정지 | COM Trigger를 먼저 검증. CAPL 필수라고 볼 근거 없음. |
| 측정을 유지하며 매 구간 BLF 파일 완결 | 기존 파일 분리 설정으로 충족하는지 우선 확인. 부족하면 closeLogFile 등의 보조 제어를 검토. |
| CAN ID별 마지막 수신 시각·주기 이상 감시 | CANoe 안에서 이벤트·타이머로 처리하고 요약 상태를 외부로 전달하는 CAPL 설계가 유력한 후보. |
| 버스·장치 이상 감시 | CANoe/장비가 제공하는 관측값을 먼저 확인. CAPL을 넣는 것만으로 모든 장치 분리·물리 단선을 판별할 수 있지는 않음. |
| Ethernet PCAP 기록 | dumpcap이 담당. CAPL에서 Ethernet 원본 패킷을 다시 저장할 이유는 현재 없음. |
| Wireshark 창 실행·정지 관리 | 외부 실행부가 담당. CAPL에서 프로세스 제어까지 맡길 필요 없음. |

CANoe 19에는 특정 블록을 지정하는 startLogging·stopLogging과 명시적 파일 닫힘 closeLogFile이 있다. 전체 블록에 영향을 주는 인자 없는 호출을 기존 프로젝트에 무조건 추가하지 않는다. [S4, S5]

CAPL 보조 기능이 필요하면 외부 실행부와의 명령·응답을 설계한다. 예를 들어 시스템 변수에 요청 상태, 요청 번호, 적용 파일명, 응답 번호, 오류 코드, 관측 상태를 둔다. 이 이름들은 제품의 내장 API가 아니라 우리가 정의할 인터페이스다.

파일 경로 등 요청 내용을 먼저 쓰고 요청 번호를 마지막에 갱신한다. 같은 요청의 재전송으로 기록이 다시 토글되지 않도록 처리한다. 응답은 명령 수신·적용과 실제 파일 검증을 구분한다. CAPL 함수를 COM에서 직접 호출하는 경로도 공식 제공되지만, 초기화 시점·측정 재시작 시 함수 참조 재취득 조건을 구현 전에 확인한다. [S9]

감시 CAPL의 배치도 검토 대상이다. Vector는 Measurement Setup의 CAPL 노드가 메시지 전달을 막는 필터로 동작할 수 있음을 설명한다. 기존 로깅 경로에 노드를 무심코 직렬 삽입하지 말고, 배치 전후 실제 프레임·이벤트가 동일하게 기록되는지 검증한다. [S10]

## 6. Wireshark: 현행 동작과 외부 제어를 구분

### 6.1 현행 기본 캡처 동작

출력 경로를 지정하지 않은 기본 동작에서는 캡처를 시작하면 패킷이 실시간 목록에 표시되고, 임시 캡처 파일에 기록된다. 캡처 중지는 패킷 취득을 멈추는 동작이고, Save / Save As는 취득한 데이터를 사용자가 지정한 이름·위치·형식으로 보관하는 동작이다. 출력 파일을 처음부터 지정해 그 파일에 기록하는 설정도 있다. [S15, S16]

```text
캡처 시작 → 실시간 목록 확인 + 임시 파일 기록 → 캡처 중지
                                                  ├─ 파일 저장
                                                  └─ 보관하지 않고 새 캡처
```

Restart는 기존 캡처를 버리고 같은 옵션으로 다시 취득하는 편의 동작이므로, 완료된 시험의 보관 절차와 구분한다. [S17]

통합 패널이 자동 저장하도록 만들면 내부의 캡처 중지와 파일 보관을 정지 버튼 한 번에 처리할 수 있다. 이를 '저장 → 종료 → 다시 저장'으로 설명하지 않는다.

### 6.2 안 A: 기존 Wireshark GUI의 동작을 제어

Wireshark 자체가 NIC에서 취득하면 실시간 패킷 목록과 상세 해석을 그대로 볼 수 있다. 별도 파일 추적·named pipe 표시 계층이 필요한 것은 아니다.

CANoe COM과 동일한 범용 외부 제어 인터페이스가 Wireshark GUI에도 있다고 가정하지 않는다. 공식 명령행의 캡처 시작·출력 경로 지정, 실행 중 GUI의 정지·저장·다시 시작을 외부에서 어떻게 호출할지 검토한다. GUI 자동화가 필요하면 대상 창 식별, 실행 상태, 저장 대화상자, 이름 충돌·실패 응답, 사용자가 Wireshark에서 직접 조작한 상태와의 동기화를 확인한다.

설계 난점은 Wireshark가 패킷을 취득·저장할 수 있는지가 아니라 이 일련의 기능을 통합 패널이 안정적으로 호출하고 결과를 확인하는 방법이다.

### 6.3 안 B: 캡처 실행부를 별도로 관리

GUI 제어보다 직접적인 캡처 프로세스 제어가 적합하면 dumpcap 등을 사용한다. dumpcap은 PCAP/PCAPNG 파일 기록을 지원한다. 이 안에서도 임시 세션 파일을 사용하고 구간 종료 후 최종 이름으로 보관하는 흐름을 구성할 수 있다. [S7]

단, dumpcap이 NIC 캡처를 맡을 경우 이미 켜둔 Wireshark가 그 캡처를 자동으로 공유하는 것은 아니다. 관찰용 입력을 연결하거나 패널에 요약을 표시해야 한다. 공식 named pipe 입력은 이 경우의 대안이다. 이전 검토의 PCAP 증분 읽기·스트림 분배는 이 안에만 속하며 아직 검증된 구현이 아니다. [S8]

이 안을 선택한다면 관찰 지연·처리량과 관찰 창 종료가 원본 취득에 주는 영향을 검증한다. 기존 GUI를 그대로 쓰는 안보다 반드시 단순하다고 단정하지 않는다.

### 6.4 자동 감시

자동 감시는 사용자의 육안 확인과 함께 제공할 기능이다. 캡처 제어·미리보기와는 별도로 필요한 관측값을 정의한다. TShark 필드 출력 등은 관측 경로의 후보이며, 어떤 구성이든 실제 취득 범위·처리 지연·필터를 명확히 한다. [S11]

소스·주기 기준은 사용자 요청대로 추후 확정한다. 현재는 MAC/IP/포트·프로토콜·수신 주기를 임의로 채워 정상·이상을 판정하지 않는다. PC 링크, 대상 트래픽 미수신, 캡처 도구 오류는 구분한다.

## 7. 안 B 선택 시 Windows 캡처 프로세스 정지 검토

시작만 성공하고 정지 때 강제 종료하는 구현은 부적절하다. dumpcap 공식 소스에는 Windows 콘솔 제어 이벤트를 받아 캡처 루프를 종료하는 처리가 있다. 다만 시험 PC의 설치 버전에서 확인해야 한다. [S12]

후보 구현은 GUI와 분리된 숨김 캡처 실행부가 콘솔·프로세스 그룹을 관리하고, 자기 캡처에만 정상 정지 이벤트를 전달한 뒤 종료·쓰기 완료를 기다리는 방식이다. Microsoft 문서상 GenerateConsoleCtrlEvent에는 콘솔 공유·그룹 지정 조건이 있으므로 '콘솔 없는 프로세스를 띄우고 PID로 Ctrl+C를 보내면 된다'고 가정하지 않는다. [S13]

정지 시간 초과·앱 종료·관측 프로세스 중단·오류 메시지 출력이 계속되는 경우도 확인한다. 표준출력·오류출력은 지속적으로 읽어 프로세스가 출력 버퍼에서 멈추지 않도록 한다. 다른 사용자의 Wireshark·CANoe를 함께 종료하는 프로세스명 기반 일괄 종료는 사용하지 않는다.

## 8. 통합 시작·정지의 실제 동작 제안

### 시작

1. 선택한 CANoe 인스턴스·프로젝트·Logging Block과 캡처 인터페이스·저장 공간을 확인한다.
2. CANoe 측정은 사용자가 번개 버튼으로 시작해 유지하는 현행 흐름을 기준으로 한다. 기록 시작 요청이 전체 측정을 재시작하지 않게 한다.
3. 고유 세션 ID와 충돌 없는 PCAP·BLF 경로/규칙을 준비한다. 세션과 실제 생성 파일의 대응을 기록한다.
4. Ethernet 취득 준비를 확인한 뒤 CANoe 기록 시작을 요청하는 순서를 우선 검토한다. 시작 시각 오차와 준비 시간을 기록한다.
5. 각 경로의 확인 결과로 상태를 갱신한다. 하나만 성공하면 부분 시작으로 표시하고 미리 정한 정리 정책을 따른다.
6. 안 A에서는 Wireshark 자체 실시간 표시를 사용한다. 안 B에서는 관찰 입력 또는 패널 요약을 연결한다.

### 정지

1. 종료 처리로 전환하고 새 시작·중복 정지 요청을 막는다.
2. CANoe 기록 구간을 종료한다. post-trigger가 설정돼 있다면 해당 구간까지 포함하는지 확인한다.
3. 필요한 CANoe 후행 구간까지 포함하도록 Ethernet 종료 순서를 조정하고, 두 파일의 실제 취득 범위를 기록한다.
4. Wireshark 캡처를 중지하고 해당 구간을 PCAP으로 보관한다. CANoe는 현행 구간 기록 종료 결과를 확인한다. 이 전체 처리를 통합 정지 버튼 한 번에 묶을 수 있다.
5. PCAP은 capinfos 등으로 형식·읽기·패킷 수·범위를 확인하고, BLF는 사용 가능한 Vector 도구 또는 검증된 판독기로 별도 확인한다. [S14]
6. 두 파일이 요구조건을 만족하면 세션을 완료로 표시한다. 다음 시작은 항상 새 파일을 사용한다.

한 버튼 제어는 동시에 명령하는 사용자 경험을 의미한다. PC·NIC·Vector 장비의 실제 타임스탬프가 정확히 일치한다는 보장이 아니다. 세션 요청 시각, 도구의 시작 확인 시각, 파일 내 패킷/이벤트 시각을 구분한다.

## 9. 현재 시안에서 실제 구현 전에 바꿔야 할 부분

| 검토 항목 | 문제와 필요한 처리 |
| --- | --- |
| 도구별 상태 관리 | 실제 PCAP·BLF 취득 상태를 각각 받아 표시해야 한다. 두 상태를 하나의 화면 변수만으로 성공 처리하지 않는다. |
| 대기/캡처 중 두 상태만 표현 | 최소한 준비 확인, 시작 처리, 종료 처리, 오류·부분 실패를 표현해야 한다. 창 크기는 작게 유지할 수 있다. |
| 버튼 클릭 후 즉시 성공 표시 | 명령 전송 성공, 실제 취득 상태, 저장 완료를 분리한다. |
| 정지 버튼의 의미 | 두 구간의 취득을 멈추고 이번 PCAP·BLF 파일 쌍을 보관하는 자동화 작업으로 정의한다. 내부 캡처 중지와 최종 보관은 구분한다. |
| 창 닫기 | 창 숨김과 취득 정지·프로그램 종료를 구분한다. 저장 중 창이 사라져도 상태를 회수할 수 있어야 한다. |
| 한쪽 오류 | 다른 경로의 실제 상태와 보존된 파일을 보여주고, 전체 성공으로 표시하지 않는다. |
| 기존 측정과 충돌 | 잘못된 인스턴스 연결·기존 취득 인계·전체 측정 정지 여부를 명시적으로 관리한다. |

현재 시안이 실제 도구 연동 전이라고 표시한 점은 맞다. 위 항목은 시안 결함 단정이 아니라 실제 제어로 확장할 때의 설계 조건이다.

## 10. 본개발 전에 수행할 최소 실증

| 순서 | 실증 | 통과 조건 |
| --- | --- | --- |
| POC-1 | CANoe COM 읽기 연결 | 실제 19 버전·프로젝트·로깅 블록을 식별한다. 기존 측정이나 설정을 임의로 변경하지 않는다. |
| POC-2 | 현행 로깅의 외부 제어 재현 | 기존 패널에서 이미 되는 구간 저장을 외부 명령으로 두 번 재현한다. 기존 설정과 같은 구간·파일 결과 및 PCAP과의 대응을 확인한다. |
| POC-3 | Wireshark 제어 흐름 재현 | 선택한 제어 안으로 캡처 시작·중지·PCAP 보관·다음 구간 시작을 수행한다. 실제 GUI와 외부 패널의 상태가 일치한다. |
| POC-4 | 실시간 확인과 제어 상태 | 안 A는 Wireshark 자체 목록과 제어 상태 동기화를 확인한다. 안 B를 선택한 경우에만 별도 실시간 표시 연결의 지연·부하를 검증한다. |
| POC-5 | 한 버튼 통합 | 두 개의 파일 쌍을 연속 취득하고 시작·종료 오차와 파일 대응이 기록된다. 부분 실패·중복 클릭도 확인한다. |
| POC-6 | 부하·파일 오류 | 실제 예상 부하에서 CPU·메모리·저장량·캡처 누락·관측 지연을 측정한다. 디스크 부족·도구 오류를 성공으로 표시하지 않는다. |

소스별 자동 경고 실증은 사용자가 기준을 제공한 후 추가한다. 통합 캡처·저장·사람의 실시간 관찰은 그 기준과 독립적으로 검증할 수 있다.

## 11. 남은 확인 항목

- 기존 Logging 패널이 기본 CANoe 기능인지, 사용자 정의 패널인지와 대상 블록·트리거·필터.
- 프로젝트에 CAPL·시스템 변수를 추가할 수 있는지.
- CANoe 19 상세 빌드·제품 에디션과 시험 PC의 운영체제·배포 제약.
- CANoe 측정이 미실행인 경우 사용자에게 준비 필요로 알릴지 등 예외 처리. 정상 흐름은 기존 측정을 유지한 구간 기록이다.
- 시험 NIC 수와 캡처 드라이버·Wireshark/dumpcap 버전, 실제 데이터량·최장 취득 시간.
- 허용되는 사람의 미리보기 지연, 향후 자동 경고 지연.
- 소스·정상 주기 조건은 사용자 요청대로 추후 확인한다.

현행 CANoe 구간 로깅과 Wireshark의 캡처·표시·저장 기능은 기준 동작으로 받아들인다. 아직 수행하지 않은 것은 통합 패널을 통한 외부 제어의 실증이다. 기존 기능의 존재 확인과 새 연동의 결과 검증을 혼동하지 않는다.

## 12. 공식 근거

CANoe 19 도움말은 Vector의 CAPL Documentation 안내(KB0011332)에서 연결된 공식 온라인 도움말을 브라우저로 열어 확인했다. 일부 동적 도움말은 일반 웹 추출에서 읽히지 않아 실제 표시된 본문과 확장 설명을 확인했다. 별도 실행 테스트는 하지 않았다.

- [S1 — CANoe 19 COM Interface](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/COMInterface/COMInterface.htm)
- [S2 — CANoe 19 Logging COM Object](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/COMInterface/Objects/COMObjectLogging.htm)
- [S3 — CANoe 19 Trigger COM Object](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/COMInterface/Objects/COMObjectTrigger.htm)
- [S4 — CANoe 19 startLogging](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/CAPLFunctions/Other/Functions/CAPLfunctionStartLogging.htm)
- [S5 — CANoe 19 closeLogFile](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/CAPLFunctions/Other/Functions/CAPLfunctionCloseLogFile.htm)
- [S6 — CANoe 19 Logging File Configuration](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/CANoeCANalyzer/FunctionBlocks/Logging/LoggingFileFormat.htm)
- [S7 — Wireshark dumpcap Manual](https://www.wireshark.org/docs/man-pages/dumpcap.html)
- [S8 — Wireshark CaptureSetup/Pipes](https://wiki.wireshark.org/CaptureSetup/Pipes)
- [S9 — Vector CANalyzer/CANoe as a COM Server, sections 2.5–2.7](https://cdn.vector.com/cms/content/know-how/_application-notes/AN-AND-1-117_CANoe_CANalyzer_as_a_COM_Server.pdf)
- [S10 — Vector CAN Statistics System Variables, KB0012859](https://support.vector.com/kb/?id=kb_article_view&sysparm_article=KB0012859)
- [S11 — Wireshark TShark Manual](https://www.wireshark.org/docs/man-pages/tshark.html)
- [S12 — Wireshark dumpcap source](https://github.com/wireshark/wireshark/blob/master/dumpcap.c)
- [S13 — Microsoft GenerateConsoleCtrlEvent](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent)
- [S14 — Wireshark capinfos Manual](https://www.wireshark.org/docs/man-pages/capinfos.html)
- [추가 근거 — CANoe 19 Trigger Configuration](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/CANoeCANalyzer/FunctionBlocks/Trigger/TriggerConfiguration.htm)


- [S15 — Wireshark Capture Files and File Modes](https://www.wireshark.org/docs/wsug_html_chunked/ChCapCaptureFiles.html)
- [S16 — Wireshark Saving Captured Packets](https://www.wireshark.org/docs/wsug_html_chunked/ChIOSaveSection.html)
- [S17 — Wireshark Stop and Restart Capture](https://www.wireshark.org/docs/wsug_html_chunked/ChCapRunningSection.html)


## 13. CAPL 미사용과 CANoe 복수 실행 추가 검토

2026-10-17 사용자 추가 설명: 서로 다른 RBS 구성으로 CANoe를 두 개 동시에 실행하기도 한다. 파일은 .cfg인 것으로 추정된다. 시험마다 한쪽 또는 양쪽의 로깅을 선택한다. 통합 프로그램이 CANoe를 실행해도 되며, 이미 열린 창에 연결하는 방식도 함께 지원하면 좋다.

### 13.1 기존 버튼에 CAPL·시스템 변수가 없어도 가능한 경로

CANoe의 표준 Logging Block은 COM 객체로 제공되며 Trigger.Start/Stop으로 제어하는 경로가 있다. 따라서 기존 버튼에 사용자 정의 CAPL·시스템 변수가 연결돼 있어야만 외부 제어가 가능한 것은 아니다. 기존 버튼이 어떤 블록과 설정을 제어하는지 확인하고, 동일한 기록 동작이 되는 표준 제어 경로를 선택한다.

COM으로 필요한 제어를 할 수 없고 프로젝트 수정도 허용되지 않는 경우에는 현재 확인한 근거만으로 완전한 비화면 제어를 보장할 수 없다. 이 경우 지원되는 다른 제어 경로를 확인하거나 화면 자동화·지원 범위를 별도 결정한다. CAPL이 필수라고 가정하거나 자동으로 마우스 조작으로 전환하지 않는다.

CAPL은 CANoe 내부에서 메시지·타이머·변수 이벤트에 반응하는 동작을 작성하는 C와 유사한 언어다. 사용자가 기존 코드의 존재나 작성법을 알고 있어야 이 프로젝트를 진행할 수 있다는 의미는 아니다.

### 13.2 RBS와 .cfg

이 업무 맥락에서 RBS는 Restbus Simulation 또는 Remaining Bus Simulation, 즉 시험 대상 이외 ECU의 통신을 대신 재현하는 구성을 뜻할 가능성이 높다. 현장에서 그 구성 묶음을 RBS로 부르는 것으로 해석하며, 해당 조직의 정확한 용례는 미확정이다.

.cfg는 CANoe의 구성 파일이다. 패널·로깅 블록·네트워크·데이터베이스·시뮬레이션 등의 설정을 담거나 관련 파일을 참조할 수 있으므로 프로젝트 파일처럼 이해할 수 있다. RBS가 .cfg라는 확장자 자체를 뜻하는 것은 아니다.

### 13.3 인스턴스 식별과 COM 연결을 구분

- Windows에서 두 프로세스·창을 식별하는 것과, 각각에 대응하는 CANoe COM 객체를 얻는 것은 별도 작업이다.
- CANoe.Application으로 한 번 연결하는 예제나 변수 두 개를 만드는 것만으로 특정 두 창에 독립 연결된다고 보장하지 않는다.
- CANoe 19의 Configuration.FullName을 읽어 실제 연결된 프로젝트 전체 경로와 사용자가 선택한 경로를 비교할 수 있다. 이것은 연결 결과를 검증하는 수단이며 임의 PID의 COM 객체를 얻는 기능을 뜻하지 않는다.
- 공식 실행 옵션 /m은 복수 인스턴스의 서로 다른 application name과 하드웨어 채널 할당에 관련된다. 이를 COM 인스턴스 선택 옵션으로 오해하지 않는다. 이름을 바꾸면 기존 채널 매핑과의 관계도 확인해야 한다.
- 이미 열린 두 인스턴스 모두에 독립 COM 연결하는 일반적인 방법은 이번 공식 문서 검토에서 확인하지 못했다. CANoe 19 상세 빌드·실제 설정에서 연결 방식과 제약을 실증해야 한다.
- 통합 프로그램이 실행을 맡을 수 있으므로 시작 단계부터 대상과 연결 참조를 관리하는 안을 먼저 검토할 수 있다. 이 경우에도 COM 객체가 실제로 서로 다른 인스턴스에 대응하는지 확인해야 하며, 별도 실행했다는 이유만으로 보장하지 않는다.

### 13.4 패널 설계 조건

예시로 'CANoe A / 구성 A.cfg / 로깅 선택', 'CANoe B / 구성 B.cfg / 로깅 선택'을 표시한다. 파일명뿐 아니라 전체 경로와 검증된 연결 상태를 보관한다. OS 프로세스 식별 정보는 대응 관계를 확인할 수 있을 때 함께 기록한다.

기록 시작 전 선택한 구성과 실제 COM 연결 구성, 대상 Logging Block, 현재 측정 상태가 일치하는지 확인한다. 불일치·연결 모호성은 '대상 확인 불가'로 표시하고 기록 명령을 보내지 않는다. 인스턴스 종료·프로젝트 교체 시 기존 참조를 무효화하며 다른 CANoe로 자동 연결을 돌리지 않는다.

양쪽 CANoe를 선택하고 Ethernet 인터페이스 하나를 함께 취득하는 경우 결과는 원칙적으로 PCAP 하나와 CANoe별 BLF 두 개가 된다. 이는 기존 '한 파일 쌍' 모델을 다중 대상 세션으로 확장하는 경우다. 파일명과 결과 요약에 구성별 대응을 기록한다.

### 13.5 추가 검증 기준

1. 서로 다른 구성 A·B를 열고 A만 제어했을 때 B의 기록·측정 상태가 바뀌지 않는다.
2. B만 제어했을 때 A가 바뀌지 않는다. 두 연결이 같은 인스턴스를 가리키지 않는지 확인한다.
3. 둘 다 선택했을 때 각 BLF가 올바른 구성에 대응하고 결과를 개별 표시한다.
4. 한쪽 종료·재시작·.cfg 교체 시 다른 쪽에 잘못된 명령이 전달되지 않는다.
5. 같은 기본 파일명·다른 경로의 .cfg도 구분한다. 같은 .cfg를 두 번 연 경우에는 경로만으로 구분하지 않고 모호성 처리 또는 추가 식별이 필요하다.
6. 통합 프로그램 실행 모드와 이미 열린 창 연결 모드는 각각 검증한다.

추가 공식 근거:

- [CANoe 19 Configuration COM 객체 — FullName 확장 설명](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/COMInterface/Objects/COMObjectConfiguration.htm)
- [CANoe 19 Command Line Parameters — /m, /f](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/CANoeCANalyzer/General/CommandLineParameter.htm)
- [Microsoft GetActiveObject — 실행 중 COM 객체 조회](https://learn.microsoft.com/en-us/dotnet/fundamentals/runtime-libraries/system-runtime-interopservices-marshal-getactiveobject)
- [Vector CAPL Basics](https://elearning.vector.com/course/view.php?id=158&section=1)

## 14. .cfg 지정 실행으로 범위 확정

2026-10-17 사용자 결정: 이미 열린 CANoe 두 창에 자유롭게 연결하는 기능은 제외한다. 사용자가 .cfg 경로를 입력·선택하고 통합 프로그램이 해당 구성을 실행하는 방식만 지원한다. 이 결정이 13절의 '이미 열린 창 연결도 선호'하던 범위를 대체한다.

- 실행한 CANoe는 사용자가 일반 화면에서 직접 조작·설정 수정할 수 있게 한다. 편집 가능 범위는 제품 에디션·권한·측정 상태에 따른다. 통합 프로그램으로 실행했다는 이유로 별도의 편집 잠금을 두지 않는다.
- 사용자는 필요하면 설정을 수정·저장하고 측정을 시작한 후, 통합 패널에서 구간 취득을 시작·정지한다. 측정 자동 시작은 별도 확정 전이다.
- 기존 창을 임의로 인계하거나 새 .cfg를 기존 창에 덮어 열지 않는다. 새로 실행·관리하는 대상과 실제 연결 객체의 대응을 검증한다.
- 실행 후 같은 구성을 편집하는 것은 허용한다. 로깅 블록·저장 위치·채널 등 제어 관련 설정은 다음 기록 명령 전에 다시 읽어 확인한다.
- 창에서 프로젝트를 다른 .cfg로 교체하거나 닫으면 현재 대상 연결을 유효하다고 유지하지 않는다. 재확인 전에는 다음 기록 명령을 보내지 않는다.
- 사용자 수정 사항을 이전 값으로 자동 되돌리거나 원본 .cfg에 자동 저장하지 않는다. 세션에는 실제 적용된 설정과 출력 파일 대응을 기록한다.
- 복수 실행의 COM 연결·제어 분리는 여전히 실제 19 환경에서 실증할 항목이다. 실행 방식을 좁힌 것과 독립 COM 연결 검증 완료는 구분한다.

제품별 편집 범위 근거: [Vector CANoe Product Concept](https://www.vector.com/en/product/canoe/product-concept/).
