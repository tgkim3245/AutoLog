# 사내 PC 1대용 Npcap 설치 파일 동봉

사용자가 같은 회사 내부 PC 1대에 전달한다고 확인한 요청에 맞춰 Npcap 설치 파일을 포함하는 빌드 옵션을 추가했다. 앱 실행/취득 코드는 변경하지 않아 SW는 0.9.21을 유지하고 문서 개정을 `2026-10-23.9`로 올렸다.

`build.cmd --include-npcap-internal`은 `One Click Log-0.9.21-internal_<시각>` 형태의 별도 배포 폴더/ZIP을 만든다. Npcap 1.90 공식 설치기를 `installers/Npcap/npcap-1.90.exe`에 원본 그대로 복사하고, 공식 LICENSE·세 언어 설치 안내·파일 해시 목록을 같은 폴더에 넣는다. 설치된 PC에서는 재설치할 필요가 없으며 새 PC에서 사용자가 관리자 권한으로 공식 설치창을 진행한다. 자동/무인 설치 옵션은 사용하지 않고, 빌드 중 설치기 실행·드라이버 추출·현재 PC 설치/변경을 하지 않는다.

일반 빌드는 Npcap을 포함하지 않는다. Wireshark CLI의 `drivers_included=false`는 해당 CLI 폴더의 구성을 뜻하며, 내부 배포의 별도 설치기는 `build_info.json`의 `npcap_installer` 및 `distribution_scope=internal-single-pc`로 기록한다. 내부 동봉본을 외부 배포물로 전용하지 않는다. 공식 설치기 바이너리와 개인 경로는 Git에 넣지 않는다.

공식 다운로드 `https://npcap.com/dist/npcap-1.90.exe`의 1,325,256바이트 원본을 검토했다. SHA256은 `682b57e1c05ef375931975c9d6ded40888f4bfdf9f4b11571e654f962f1199b6`이며 Windows Authenticode 상태 Valid, 서명 주체 Nmap Software LLC를 확인했다. 빌드에서도 파일 크기/SHA256·서명을 다시 확인하고 복사 후 해시를 대조한다. 캐시 변조·서명 오류·다른 출처·다른 배포 범위는 실패로 처리한다. 공식 라이선스는 고정 Git 커밋과 해시로 추적한다.

공식 조건 확인: [Npcap 다운로드/사용 범위](https://npcap.com/#license), [공식 EULA](https://github.com/nmap/npcap/blob/1a898a3a988c2a8e2d767027ccff28c20024188c/LICENSE). 무료 사용 대수와 외부 재배포 권한은 별개다. 이 작업은 사용자가 확인한 내부 1대 전달 범위를 대상으로 하며 외부 재배포 권한을 제공하지 않는다.

관련 자동 검사 46개 통과: 원본 설치기/라이선스/안내문/해시 포함, 기본 빌드의 제외와 내부 ZIP의 포함, 캐시 변조·서명 오류 차단, PowerShell 인자와 경로 처리, 가이드 원문/세 언어·사진·문서 해시 일치. Ruff와 git diff --check 통과. 실제 새 PC의 설치·재부팅·취득 검증은 별도다.

가이드는 세 언어의 데스크톱/360px 화면·설치 상세 링크·사진 확대·언어 기억을 포함한 44개 화면으로 확인했다. 상세 제목이 고정 목차 아래 가려지지 않도록 링크 이동 여백도 조정했다. 앱 코드와 SW 버전을 유지한 포장/문서 변경이므로 캡처 전반의 새 차량 시험을 수행한 것으로 표현하지 않는다.
