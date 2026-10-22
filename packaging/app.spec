# Build on Windows using the verified project interpreter.
from pathlib import Path
from importlib.metadata import distribution
import sys

project_root = Path(SPECPATH).parent
sys.path.insert(0, str(Path(SPECPATH)))
from build_release import read_app_metadata, windows_version_info

app_name, app_version = read_app_metadata(project_root)
license_data = [(str(path), 'licenses') for path in (project_root / 'licenses').glob('*') if path.is_file()]
license_data.append((str(project_root / 'assets/one_click_log.ico'), 'assets'))
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.exists():
    license_data.append((str(python_license), 'licenses/Python'))
for package_name in ('PySide6', 'PySide6_Essentials', 'shiboken6', 'pywin32', 'pyinstaller', 'python-can', 'wrapt'):
    package = distribution(package_name)
    for relative_file in package.files or ():
        filename = str(relative_file).replace('\\', '/')
        if '.dist-info/' not in filename:
            continue
        if '/licenses/' in filename.lower() or relative_file.name in ('METADATA', 'LICENSE.txt'):
            source = Path(package.locate_file(relative_file))
            if source.is_file():
                license_data.append((str(source), 'licenses/' + filename.rsplit('/', 1)[0]))
a = Analysis(
    [str(project_root / 'src' / 'vil_logging' / '__main__.py')],
    pathex=[str(project_root / 'src')],
    binaries=[], datas=license_data, hiddenimports=['pythoncom', 'win32com.client', 'win32timezone'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtPdf',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.Qt3DCore'],
    noarchive=False,
    module_collection_mode={'can': 'py'},  # Keep the LGPL library replaceable in the distribution.
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=app_name, debug=False,
          icon=str(project_root / 'assets/one_click_log.ico'),
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          version=windows_version_info(app_name, app_version))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=app_name)
