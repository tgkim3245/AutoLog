# CANoe CAPL 컴파일의 CBF 쓰기 거부

2026-10-20 · Diag 수동 로깅 실패의 환경 진단. AutoLog 0.9.2 코드 변경이나 새 빌드는 필요하지 않다.

## 확인한 원인

사용자가 제공한 오류는 두 CAPL 소스의 컴파일 결과 `.cbf`를 원래 프로젝트 폴더에 쓰지 못했다는 내용이다. CANoe 자체의 컴파일 단계에서 실패한 것이며 AutoLog의 BLF 시작 제어와 구분한다.

이 PC에서 읽기 전용으로 확인한 근거:

- Windows Defender 제어된 폴더 액세스는 차단 모드(`EnableControlledFolderAccess=1`)다.
- **2026-10-20 10:33:24 KST**, Defender Operational **이벤트 1123 두 건**이 `CAPLcompExec.exe`의 Diag 프로젝트 노드 폴더·테스트 모듈 폴더 쓰기를 각각 차단했다. 사용자 오류의 두 `.cbf` 출력 폴더와 일치한다.
- **10:31:30 KST**에는 `CANoe64.exe`도 같은 Diag 프로젝트 폴더 쓰기를 차단당했다.
- 해당 `.can`/`.cbf` 네 파일은 읽기 전용이 아니며 현재 사용자에게 파일 시스템 FullControl이 있다. 이 권한만으로 Defender의 별도 쓰기 차단이 해제되지는 않는다.
- 설치된 `CAPLcompExec.exe`와 `CANoe64.exe`의 Authenticode 서명은 모두 Valid, 서명자는 Vector Informatik GmbH다.

Windows 보안 이벤트의 앱과 경로가 실제 오류와 일치하므로 이번 쓰기 거부의 원인은 Defender CFA로 확인했다. 파일 잠금이나 CAPL 소스 수정을 먼저 시도할 근거는 없다. 기존 컴파일 결과의 이용 여부에 따라 CAN 수동 기록과 Diag 재컴파일 결과가 다를 수 있으나 이 부분은 추가로 실증하지 않았다.

원본 프로젝트·CBF·보안 정책·허용 목록을 변경하지 않았으며 CANoe 측정이나 컴파일을 자동 실행하지 않았다. 업무 프로젝트 전체 경로·원본 보안 이벤트·개인 SID는 Git에 넣지 않는다.

## 조치

1. 필요한 기록/작업을 정리하고 CANoe를 닫는다.
2. **Windows 보안 → 바이러스 및 위협 방지 → 랜섬웨어 방지 관리 → 제어된 폴더 액세스를 통해 앱 허용 → 허용된 앱 추가**에서 다음 설치 파일을 지정한다. 최근 차단 앱 목록 또는 모든 앱 찾아보기를 이용한다. 메뉴/정책 변경에 관리자 권한이 필요하면 해당 PC 관리자가 처리한다.

   ```text
   C:\Program Files\Vector CANoe 19\Exec64\CAPLcompExec.exe
   C:\Program Files\Vector CANoe 19\Exec64\CANoe64.exe
   ```

3. CANoe를 다시 열고 Diag cfg를 로드해 CAPL을 재컴파일한다. `.cbf` 쓰기 거부가 사라졌는지 확인한 뒤 F9 측정·Trace 수신·수동 기록을 확인한다.
4. 이후 AutoLog 0.9.2에서 Diag의 연결 확인을 다시 수행하고 구간 기록/정지를 시험한다. 수동 패널 기록과 AutoLog 기록을 동시에 조작하지 않는다.

보호 기능 전체를 끄거나 프로젝트 폴더 전체를 백신 제외 대상으로 지정할 필요는 없다. 이 사례는 위 정확한 Vector 설치 파일의 CFA 허용 항목을 검토하는 방식으로 조치한다. CBF를 삭제하거나 CAPL/cfg 소스를 바꾸는 작업은 필요하지 않다.

재컴파일 후 새 오류가 나오면 그 오류는 별도로 확인해야 한다. 이번 진단을 실제 Diag 수신/BLF 성공 검증으로 등록하지 않는다.

Microsoft의 [CFA 이벤트 안내](https://learn.microsoft.com/en-us/defender-endpoint/controlled-folder-access-monitor)는 1123을 실제 차단, 1124를 감사 이벤트로 구분한다. [CFA 설정 안내](https://learn.microsoft.com/en-us/defender-endpoint/controlled-folder-access-configure)와 [허용 앱·보호 폴더 조정](https://learn.microsoft.com/en-us/defender-endpoint/customize-controlled-folders)을 참고한다.
