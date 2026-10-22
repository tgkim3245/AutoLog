# AutoLog 0.9.12 — Wireshark CLI 동봉

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
