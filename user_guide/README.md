# 공식 배포용 사용자 가이드

배포 사용자에게 전달하는 문서는 **AutoLog_User_Guide.html**과 **START_HERE.txt**다. `build.cmd`가 현재 소프트웨어 버전·문서 개정일을 반영해 EXE 옆에 만들고 ZIP에도 포함한다. HTML은 별도 프로그램 설치나 인터넷 없이 브라우저에서 읽을 수 있다.

## 관리 원본

- [사용자 가이드 HTML 원본](AutoLog_User_Guide.template.html)
- [배포 안내문 원본](distribution_notice.template.txt)
- [적용 버전·문서 개정](guide_metadata.json)
- [문서 변경 이력](CHANGELOG.md)

이 네 파일을 함께 관리한다. UI·연결/설치 조건·보안 허용 앱·기록/파일/복구 절차·알려진 제한이 바뀌면 해당 안내와 이력을 같은 변경에서 갱신한다. 소프트웨어 버전이 바뀌면 실제 적용 여부를 검토한 뒤 `reviewed_app_version`과 문서 개정을 갱신한다. 문서 버전이 맞지 않거나 원본이 누락되면 빌드를 중단한다. 완성 문서를 직접 수정하지 말고 관리 원본을 고친 뒤 다시 빌드한다.

`build_info.json`에는 배포에 포함한 두 문서의 파일명·바이트 수·SHA256과 적용 버전·문서 개정·갱신일을 기록한다. 같은 SW 버전에서 문서만 바뀌면 SW 번호는 유지하고 문서 개정과 빌드 시각으로 구분한다.

기존 `user_guide_draft.md`는 이 안내로 통합했다. `outline.md`와 `performance_notes.md`는 발표/성과 자료이며 배포 사용자 가이드에 포함하지 않는다.
