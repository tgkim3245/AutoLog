# AutoLog 0.9.12 — Wireshark CLI 동봉

> 과거 기록: 이 문서는 작성 당시의 변경·검증 근거를 보존합니다. 현재 동작과 남은 확인 사항은 [현재 구현 상태](../reference/implementation_status.md)를 따릅니다.

2026-10-22. 사용자는 앞선 동작을 정상 확인했다고 알린 뒤, Ethernet 캡처 도구를 배포 파일 안에 넣도록 요청했다. 정상 확인한 앱 버전/개별 항목은 별도 명시되지 않았으므로 새 패키지의 실장 검증과 구분한다.

## 배포와 빌드

- 공식 Wireshark 4.6.9 x64 MSI를 버전·파일 크기·SHA256으로 고정한다. 공식 [서명 해시 목록](https://www.wireshark.org/download/src/all-versions/SIGNATURES-4.6.9.txt)의 MSI·Wireshark 소스 해시와 대조했다. `packaging/wireshark.lock.json`이 다운로드 출처와 의존 소스/recipe를 추적한다.
- 빌드 캐시에서 검증한 MSI를 매번 새 작업 폴더로 관리 추출한다. 운영체제에 Wireshark/Npcap을 설치하지 않는다. 사용자 Wireshark 폴더나 사용자 프로필·추가 플러그인을 복사하지 않는다.
- `tools/Wireshark/`에 TShark·dumpcap·capinfos, stock plugin·프로토콜 자료와 PE import/delayed import로 추적한 런타임 DLL을 배치한다. Microsoft C++ 런타임도 MSI에서 변경 없이 앱 로컬로 둔다. Wireshark GUI와 Npcap/USBPcap 드라이버/설치기는 제외한다.
- 외부 실행 파일과 라이브러리는 변경하지 않는다. 공식 소스·의존성 upstream 소스·vendor recipe는 `third_party_sources/Wireshark/`, 저작권·라이선스 원문은 `licenses/Wireshark/`와 도구 폴더에 동봉한다. [Wireshark의 별도 프로세스/pipe 사용 안내](https://www.wireshark.org/faq.html)를 따른다. Npcap은 [별도 배포 조건](https://npcap.com/)을 따르므로 제품 묶음에 포함하지 않는다.
- 제한된 PATH에서 세 도구 버전 실행을 확인하고, runtime/resource 파일별 크기·해시를 `bundle_manifest.json`에 기록한다. `build_info.json`에도 도구 버전·manifest 해시·바이트 수·드라이버 미포함을 넣는다. 검증 실패 시 불완전 패키지를 성공으로 배포하지 않는다.
- 캐시는 산출물 루트의 `tool-cache/`에 두고 매번 크기·해시를 검증한다. 처음 빌드는 네트워크가 필요하며 이후 검증된 캐시로 재빌드할 수 있다. 캐시와 바이너리·소스 아카이브는 Git에 넣지 않는다. GPL 소스 자료 때문에 이전 배포보다 ZIP 용량이 커진다.

## 실행과 설정

- 빈 `tshark_path`는 동봉 도구 기본값이다. frozen 실행 파일을 기준으로 찾으며 배포 폴더의 절대 경로를 사용자 설정에 쓰지 않는다. 전체 배포 폴더를 옮겨도 해당 위치를 사용한다. 시스템 PATH·Program Files에서 임의 TShark를 고르지 않는다.
- 설정창에는 실제 도구 경로를 표시하고 직접 선택 기능을 유지한다. 직접 선택한 다른 설치본은 그대로 존중하며 잘못된 경로를 조용히 다른 도구로 바꾸지 않는다. 동봉 도구를 직접 골라도 빈 기본값으로 저장해 이동 가능성을 유지한다.
- 이전 AutoLog/Auto_Log/VILLogging의 관리용 Wireshark 경로는 완전한 동봉 도구 세트가 있는 경우에만 기본값으로 전환한다. 다른 사용자 설치본과 cfg·NIC·저장 규칙·인덱스는 바꾸지 않는다.
- 준비/환경 검사, 실제 recorder와 파일 검사/현재 실행 복구가 같은 도구 경로 규칙을 사용한다. 캡처 방식은 기존 dumpcap 직접 기록·TShark 독립 해석을 유지한다. 런타임의 외부 다운로드/설치·보안 설정 변경은 추가하지 않는다.
- 새 PC는 Npcap과 사용하는 CANoe/장치 환경을 별도로 준비한다. Wireshark GUI 설치는 Zipy 기록의 필수 조건이 아니다. 가이드 개정 2026-10-22.5에 새 기본값과 전체 폴더 유지·Npcap 별도 설치를 반영했다.

## 검증

기본 도구 탐색·명시 경로 유지·폴더 이동·UI 표시/저장 분리·이전 관리 경로 전환·캐시 해시/다운로드 실패·DLL 실행 실패를 검사한다. 실제 빌드 ZIP의 도구/소스/manifest를 대조하고 압축 해제 EXE의 기본 도구·이동·모의 동작과 localhost 원본 캡처를 확인한다. 새 PC 전체 환경 및 실제 차량에서 새 배포본의 CAN/Diag/Zipy 동시 취득은 별도 현장 범위다.

전체 자동 검사 596개(52.68초), Ruff·의존성·diff·문서 링크 293개를 통과했다. 공식 가이드 개정 2026-10-22.5의 12개 뷰포트에서 가로 넘침/미치환이 없었고 수정된 준비·문제 해결 안내의 실제 렌더링을 검토했다. runtime DB를 사용하는 이전 관리 도구→동봉 도구 전환에서도 NIC·저장 규칙·인덱스 유지 검사를 통과했다.

## 최종 배포 검증

설정 API에 동봉 도구 절대 경로를 직접 전달해도 빈 기본값으로 정규화하도록 공통 처리까지 보강했다. 그 뒤 전체 자동 검사 596개를 53.52초에 통과했다. 깨끗한 소스 `7b82666e5d7c25cd0855fd42a52cc820fc1d4ca1`에서 `AutoLog-0.9.12_20261022_162422`을 빌드했다.

- ZIP 267,756,615바이트. CRC·EXE 파일/제품 버전·해시를 대조했다. runtime/resource 861개(144,471,541바이트)와 source archive 39개(174,406,946바이트)를 ZIP과 압축 해제본에서 각각 크기/SHA256으로 검증했다. 소스 아카이브는 이미 압축돼 있어 ZIP에서 재압축하지 않는다. 드라이버·Wireshark GUI가 없는 것도 검사했다.
- PATH에서 Python/외부 도구 경로를 제외한 압축 해제 EXE의 모의 버튼 시작→정지→완료→X, 중국어 설정과 NIC 목록을 확인했다. 새 프로필의 `tshark_path`는 빈 값으로 유지되며 실제 실행 도구는 동봉본이었다. 첫 smoke 개발자로그 100건에 ERROR/CRITICAL이 없었다.
- 같은 ZIP의 EXE를 사용해 PCAP/PCAPNG 각각 0패킷·5패킷·재기록의 여섯 구간을 기록·정지·검사·보관했다. 생성한 localhost UDP의 원본 수와 화면 수가 일치했고, 설정이 빈 도구 기본값인 상태로 취득한 것을 DB에서 확인했다. BPF로 새로 생성한 localhost UDP 포트만 취득했으며 물리 NIC는 열지 않았다. 별도 offline ARP fixture도 해석했다.
- 압축 해제한 배포 디렉터리를 검증 폴더 안에서 실제 이동해 같은 프로필로 다시 실행했다. 변경된 실행 위치의 도구를 사용하고 빈 도구 설정을 유지했다. 별도의 이전 관리 경로 프로필도 실제 EXE에서 빈 기본값으로 전환했다. 기존 사용자 프로필이나 실행 중인 프로그램을 이 검증에 사용하지 않았다.
- 같은 EXE의 PYZ에서 추출한 `vil_logging` 코드를 개발 Python에서 실행한 154개 검사를 통과했다. 전체 새 PC 설치·차량/라이선스 CANoe 동시 시험을 의미하지 않는다.
- 가이드 개정 2026-10-22.5의 HTML 31,452바이트·START_HERE 6,257바이트는 미리보기/패키지/ZIP/압축 해제본의 내용·해시가 같았다. 최종 14개 가이드 뷰포트의 가로 넘침/치환 검사를 통과하고 변경된 준비·Ethernet·문제 해결·범위 안내를 렌더링 검토했다. 한·영·중 설정 화면도 Windows 글꼴을 등록한 offscreen 렌더링으로 확인했다.

해시:

- ZIP SHA256: `6de7b12da39b5c9b822d2c00f2f238c0f85b330c1eb0ff862f6959cddffc9801`
- EXE SHA256: `5fd1ee463eec2c96577a0c9dc1039fa29aca7f47f91c5aecbcfa6ab13fd7e6f9`
- 도구 manifest SHA256: `c5d3979488748e81abaf6386e2d23e71e625f552b174fc2b550e6f6711566a4d`

로컬 빌드 폴더의 `verification/result.json`, `verification/bundled_tools_result.json`, `verification/localhost/result.json`, `verification/capture_button_result.json`, `frozen-core/result.json`, `documentation_verification.json`, `verification/ui/`와 가이드 미리보기 `user-guide-2026-10-22.5/visual-qa/`에 근거를 보관한다. 실제 캡처·진단 로그·개인 경로는 Git에 보관하지 않는다.
