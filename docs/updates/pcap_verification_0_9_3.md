# AutoLog 0.9.3 — Zipy 단독 PCAP 추가 확인

> 과거 기록: 이 문서는 작성 당시의 변경·검증 근거를 보존합니다. 현재 동작과 남은 확인 사항은 [현재 구현 상태](../reference/implementation_status.md)를 따릅니다.

2026-10-20. 사용자가 기억한 Zipy 단독 시작 실패에 대해 선택 처리와 실제 캡처 경로를 점검했다. 해당 단독 실패의 로그는 없어 당시 원인을 확정하지 않았다. 앱 구현과 버전은 변경하지 않았다.

## 당시 로그에서 확인한 범위

기존 0.9.2 배포 폴더의 개발자로그는 전달된 리포트와 같은 582개 레코드였다. CAN 단독 시도 뒤 CAN+Zipy 동시 선택 시도가 두 번 있고, Zipy 단독 시도는 없다. 두 동시 시도에서 Ethernet prepare는 통과했으나 CAN prepare가 실패해 configure/Start를 진행하지 않았다.

현재 정책은 선택한 모든 대상의 준비가 통과한 뒤 시작한다. CAN을 함께 선택하고 CAN 준비가 실패하면 PCAP도 시작하지 않는다. Zipy만 선택하면 CAN/Diag의 준비 상태·라이선스·COM 연결은 요구하지 않는다. 이미 진행 중인 기록의 부분 실패 정책과는 별개다.

현재 저장된 NIC는 WAN Miniport (Network Monitor) 가상 어댑터였다. TShark 목록 및 dumpcap 링크 형식 조회는 성공했다. 이 결과는 실제 차량 Ethernet 수신 성공이나 당시 단독 시작 실패의 원인을 입증하지 않는다. 사용자 NIC·저장 폴더 선택은 바꾸지 않았다.

## 실제 도구 확인

- 기존 0.9.3 ZIP에서 압축 해제한 EXE에 `--verify-ethernet`을 실행했다. TShark/dumpcap/capinfos 4.6.9를 사용했다.
- PCAP·PCAPNG 각각 0패킷, 5패킷, 재시작 후 5패킷의 6개 구간을 모두 통과했다. 같은 앱 Runtime과 worker를 통해 시작·정지·전체 읽기 검사·최종 파일 보관·번호 증가를 확인했다. 요약 수와 파일의 패킷 수도 일치했다.
- 최신 소스의 실제 Runtime에서 존재하지 않는 cfg로 CAN 또는 Diag 준비 실패를 발생시켰다. 두 경우 모두 CANoe 창을 생성하기 전에 거부됐으며 번호를 소비하지 않았다. 같은 실행에서 실패 대상을 해제하고 Zipy 단독으로 재시작해 각각 20개 생성 UDP 패킷을 PCAP에 저장·검사·보관했다.
- 모든 실제 취득은 검증용 localhost 인터페이스와 생성 UDP 필터를 사용했다. 물리 NIC·차량 트래픽은 기록하지 않았다. 따라서 차량 NIC·드라이버·연결 상태에 따른 시작 문제와 현장 성능은 이 결과만으로 확정하지 않는다.

근거는 로컬 `AutoLog-0.9.3_20261020_152028/verification/pcap-followup/result.json`과 `zipy-after-canoe-failure/result.json`에 보관했다. 실제 캡처 파일·개발자로그는 Git에 넣지 않는다.

## 회귀 검사

CAN/Diag prepare 실패 뒤 같은 Runtime에서 Zipy만 선택해 재시도하는 검사 2개를 추가했다. 실패 상태가 남은 CANoe 대상에 prepare/configure/start/stop/inspect 명령을 보내지 않고 Ethernet만 완료·보관하는지 검사한다. 관련 통합/준비 검사 32개(1.25초), Ruff·diff 검사를 통과했다.

이번 확인에서 Zipy 단독 시작 실패는 재현되지 않았다. 배포판 캡처 코드를 바꾸거나 새 EXE를 만드는 근거는 발견하지 못했다. 재발 시 그 직후 버그리포트의 선택 대상, NIC, prepare/start 오류를 확인한다.
