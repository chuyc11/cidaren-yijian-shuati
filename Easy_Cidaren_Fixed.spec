# Reproducible Windows x64 onedir build; Python 3.12 + requirements-build.txt.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / name), name) for name in ('assets', 'en_core_web_sm', 'config', 'licenses')]
datas += [(str(root / name), '.') for name in ('LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md')]
binaries = []
hiddenimports = ['release_selftest']
for package in ('spacy', 'thinc'):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
for package in ('spacy', 'thinc', 'requests', 'PyQt6'):
    datas += copy_metadata(package)

a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             runtime_hooks=[str(root / 'packaging' / 'runtime_hook.py')],
             excludes=['mitmproxy', 'pytest', 'IPython', 'torch', 'tensorflow'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Easy_Cidaren_Fixed',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, contents_directory='.', icon=str(root / 'assets' / 'icon.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Easy_Cidaren_Fixed')
