# 공식 배포용 사용자 가이드

배포 사용자에게 전달하는 문서는 **One Click Log_User_Guide.html**과 **START_HERE.txt**다. `build.cmd`가 현재 소프트웨어 버전·문서 개정일을 반영해 EXE 옆에 만들고 ZIP에도 포함한다. HTML은 별도 프로그램 설치나 인터넷 없이 브라우저에서 읽을 수 있다.

메인 **사용법** 버튼(버그리포트 왼쪽)은 이 HTML을 기본 브라우저로 연다. 첫 화면은 저장 위치 → CAN·Diag → Zipy → 시작/정지 → 파일 확인의 5단계이며, 설치·오류·검증 상세는 접어 둔다. 사진을 누르면 확대하고 Esc로 닫을 수 있다. 상세 설명 안의 항목으로 링크하면 해당 접힌 영역도 자동으로 열린다. 소스 실행에서는 같은 원본으로 임시 미리보기를 만든다.

## 관리 원본

- [사용자 가이드 HTML 원본](AutoLog_User_Guide.template.html)
- [배포 안내문 원본](distribution_notice.template.txt)
- [적용 버전·문서 개정](guide_metadata.json)
- [문서 변경 이력](CHANGELOG.md)
- [화면 사진](images/)과 [재촬영 스크립트](capture_screenshots.py)

원본과 사진을 함께 관리한다. UI·연결/설치 조건·보안 허용 앱·기록/파일/복구 절차·알려진 제한이 바뀌면 해당 안내와 이력을 같은 변경에서 갱신한다. 소프트웨어 버전이 바뀌면 실제 적용 여부를 검토한 뒤 `reviewed_app_version`과 문서 개정을 갱신한다. 문서 버전이 맞지 않거나 원본이 누락되면 빌드를 중단한다. 완성 문서를 직접 수정하지 말고 관리 원본을 고친 뒤 다시 빌드한다.

화면이 바뀌면 프로젝트 Python으로 `user_guide/capture_screenshots.py`를 실행한다. 실제 Qt 위젯에 설명용 경로·상태만 넣으며 CANoe·장비·Runtime을 연결하지 않는다. 실제 cfg·캡처·개인 경로를 넣지 않는다. 결과 PNG 12장과 `images/manifest.json`을 눈으로 확인한 뒤 함께 커밋한다. 원본 HTML의 `{{IMAGE:파일명.png}}`는 공통 렌더러 `src/vil_logging/documentation.py`가 PNG data URL로 바꾼다. 사진은 HTML 안에 포함되므로 사용자는 사진 폴더를 따로 복사할 필요가 없다. 누락·잘못된 PNG는 빌드를 중단한다. 렌더 후 데스크톱·작은 화면에서 넘침, 확대/닫기, 접힌 상세 링크를 확인한다.

`build_info.json`에는 배포에 포함한 두 문서의 파일명·바이트 수·SHA256과 적용 버전·문서 개정·갱신일을 기록한다. 같은 SW 버전에서 문서만 바뀌면 SW 번호는 유지하고 문서 개정과 빌드 시각으로 구분한다.

기존 `user_guide_draft.md`는 이 안내로 통합했다. `outline.md`와 `performance_notes.md`는 발표/성과 자료이며 배포 사용자 가이드에 포함하지 않는다.
