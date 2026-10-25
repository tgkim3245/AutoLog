# 개발과 지원 도구

| 파일 | 용도 |
| --- | --- |
| [Initial_Setup.bat](Initial_Setup.bat) | 배포 EXE 옆에 동봉. 설치된 CANoe 검색·버전 선택 후 공식 COM 등록과 Npcap 관리자 설치 통합. [사용 안내](../docs/guides/canoe_registration_helper.md) |
| [build_vehicle_test_document.py](build_vehicle_test_document.py) | 실차 TC Markdown으로 입력형 HTML 생성. --check는 최신성만 검사 |
| [check_docs.py](check_docs.py) | 로컬 문서 링크·앵커·개인 경로 검사 |

BAT의 --check는 설치·등록을 실행하지 않고 도구 발견·서명·해시·현재 COM 대상과 Npcap 파일 존재를 검사한다. 기본 더블클릭은 Windows 관리자 권한 승인을 거쳐 공식 도구를 실행하므로 CANoe와 One Click Log를 먼저 저장·종료한다. 지원 도구는 앱 실행 시 자동 호출하지 않는다.
