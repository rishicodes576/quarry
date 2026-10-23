"""Collect only shared libraries actually linked by Python and installed extensions.

The output contains an inventory so minimization does not erase component provenance.
Interactive terminal extensions are not part of the service runtime.
"""
import hashlib
import json
import pathlib
import shutil
import subprocess

root = pathlib.Path('/runtime-libs')
root.mkdir()
status_root = pathlib.Path('/runtime-status')
status_root.mkdir()
inventory = []
for pattern in ['_curses*.so', 'readline*.so', '_uuid*.so']:
    for path in pathlib.Path('/usr/local/lib/python3.12/lib-dynload').glob(pattern):
        path.unlink()
inputs = [pathlib.Path('/usr/local/bin/python3.12'), *pathlib.Path('/usr/local/lib').rglob('*.so'), *pathlib.Path('/usr/local/lib').rglob('*.so.*')]
libraries = set()
for path in inputs:
    result = subprocess.run(['ldd', str(path)], capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        value = line.strip().split(' => ')[-1].split(' (')[0]
        if value.startswith('/') and not value.startswith('/usr/local/'):
            libraries.add(pathlib.Path(value))
for path in sorted(libraries):
    # Distroless supplies glibc and OpenSSL; retain its maintained versions.
    if path.name.startswith(('libc.so', 'libm.so', 'libpthread.so', 'libdl.so', 'librt.so', 'libresolv.so', 'ld-linux', 'libssl.so', 'libcrypto.so')):
        continue
    shutil.copy2(path.resolve(), root / path.name)
    package = subprocess.run(['dpkg-query', '-S', str(path.resolve())], capture_output=True, text=True, check=True).stdout.strip().split(': /')[0]
    status = subprocess.run(['dpkg-query', '-s', package], capture_output=True, text=True, check=True).stdout
    (status_root/(package.replace(':','_')+'.status')).write_text(status)
    inventory.append({'path': str(path), 'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(), 'package':package, 'status':status})
(root/'quarry-libraries.json').write_text(json.dumps(inventory,indent=2))
