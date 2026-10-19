# 개발 빌드의 외부 구성요소

이 앱은 Python, Qt/PySide6·Shiboken, pywin32, python-can·wrapt, SQLite와 PyInstaller 실행 지원 코드를 사용한다. 실제 버전은 배포 폴더의 `requirements.lock`과 빌드 정보에서 확인한다.

- Python: https://docs.python.org/3/license.html
- Qt for Python / PySide6 / Shiboken: https://doc.qt.io/qtforpython-6/licenses.html
- Qt: https://doc.qt.io/qt-6/licensing.html
- pywin32: https://github.com/mhammond/pywin32
- python-can 4.6.1 (LGPL-3.0-only): https://github.com/hardbyte/python-can/tree/4.6.1 — 원본 소스·변경 내역은 해당 공개 저장소와 PyPI 소스 배포에서 제공한다. 라이브러리는 수정하지 않았으며 배포의 `_internal/can/`에 Python 소스로 두어 호환 버전으로 교체할 수 있다. 해당 라이브러리와의 사용을 위한 수정·디버깅을 제한하지 않는다.
- wrapt 1.17.3 (BSD): https://github.com/GrahamDumpleton/wrapt/tree/1.17.3
- SQLite: https://www.sqlite.org/copyright.html
- PyInstaller: https://pyinstaller.org/en/stable/license.html

빌드 설정은 설치된 패키지에 동봉된 라이선스·메타데이터와 Python 라이선스 파일을 `_internal/licenses/`에 복사한다. 이 문서는 원 저작권 고지와 라이선스를 대체하지 않는다. 실제 도구·드라이버·업무 구성·차량 로그는 앱 폴더에 포함하지 않는다.

현재 결과물은 기본 앱과 모의 동작을 검증하는 개발 빌드다. 팀 운용판은 개발·배포 계획의 실제 도구·장시간·오프라인·라이선스 자료 검토를 완료한 뒤 별도로 만든다.
