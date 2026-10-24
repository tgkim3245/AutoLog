# 0.2.1 — Wireshark 연결 확인 수정

> 과거 기록: 이 문서는 작성 당시의 변경·검증 근거를 보존합니다. 현재 동작과 남은 확인 사항은 [현재 구현 상태](../reference/implementation_status.md)를 따릅니다.

2026-10-18

실행: [VILLogging.exe](../../outputs/hotfix-0.2.1/VILLogging/VILLogging.exe). EXE와 `_internal`을 포함한 폴더 전체를 유지한다. 기존에 켜 놓은 앱에는 새 코드가 반영되지 않으므로 설정의 프로그램 종료로 닫은 뒤 새 EXE를 실행한다. 메인과 설정에 0.2.1을 표시한다.

## 확인한 원인과 조치

사용자가 제공한 화면과 로컬 개발자로그를 확인했다. 당시 TShark 4.6.9 버전 확인과 Windows 네트워크 6개 조회는 성공했지만, `tshark -D`에서 `Unable to load Npcap (wpcap.dll)` 오류가 났다. 실제 캡처 드라이버가 없었다. 화면은 수정 전부터 실행 중이던 Python 앱의 내용과 일치하며, 검색 완료·자동 저장 응답·미선택 안내가 반영되지 않은 상태였다.

공식 Npcap 1.89 설치 파일을 사용자 AppData에 내려받고 유효한 Nmap Software LLC 서명과 SHA256을 확인했다. 설치창은 열었지만 관리자 권한 창의 자동화 입력은 적용되지 않아 사용자가 Install/Finish를 직접 수행했고 설치 완료를 회신했다. 설치 파일을 앱 배포 폴더에 재배포하지 않는다.

- 설치 파일 SHA256: `8AED85E900D783D1308506E919587D3E540451947AF8A82F2D04F819E44305CC`
- 공식 설치 안내: [Npcap](https://npcap.com/#download), [사용자 가이드](https://npcap.com/guide/npcap-users-guide.html#npcap-installation).

수정 내용:

- Npcap이 없으면 TShark 정상 여부와 구분해 드라이버 필요·설치 링크·설치 후 다시 찾기 절차를 표시한다. Windows에서 조회한 NIC 선택 목록도 유지한다.
- 미선택/미확인 상태를 연결 오류로 바꾸지 않고 확인 필요로 안내한다.
- 이미 도착한 시작 시 검색 결과가 있으면 설정창을 열 때 중복 검색을 시작하지 않는다. 오류 응답과 30초 응답 지연에서는 검색 상태를 해제하고 다시 찾기를 활성화한다.
- 메인·설정에 실행 중인 버전을 표시하고 Fusion 스타일을 적용해 Windows에서도 테마를 일관되게 표시한다.
- `--smoke-test --smoke-discovery`로 실제 읽기 전용 도구/NIC 검색 결과가 UI 목록까지 전달되고 완료 상태가 되는지 검사할 수 있다. 기록 단계는 모의 실행이다.

## 검증과 남은 범위

자동 검사 140개 통과. Npcap 부재 안내, 기존 NIC 목록 유지, 설치 버튼, 검색 오류·시간 초과 후 재시도, 미확인을 오류로 오표시하지 않는 검사 등을 추가했다.

Npcap 설치 후 서비스 실행·`tshark -D` 성공을 확인했다. 앱에서 사용할 NPF 인터페이스 10개가 조회되며 Windows 전용 항목을 합친 UI 목록은 12개다. 원격 캡처/extcap 항목을 차량 NIC로 자동 선택하지 않는다.

Npcap 실동작은 `NPF_Loopback`에서 프로그램이 생성한 localhost UDP 패킷 1개만 필터로 취득해 PCAPNG에 저장하고, TShark로 다시 읽어 주소·시험 값·패킷 수를 확인했다. 물리 NIC나 사용자 네트워크 트래픽은 이 시험에 사용하지 않았다.

통합 앱의 실제 CANoe/TShark 취득 어댑터는 아직 구현 전이다. 이 수정의 완료 범위는 도구/드라이버 준비·NIC 목록·진단·설정 UI다. 차량 NIC의 실제 취득, CAN/Diag .cfg와 시험 PC 검증은 후속 단계다.
