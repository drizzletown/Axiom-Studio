#!/usr/bin/env python3
import hashlib,json,sys
from pathlib import Path
base=Path(__file__).resolve().parents[1]
data=json.loads((base/'SHA256_MANIFEST.json').read_text('utf-8'))
for n,h in data['files'].items():
    path=base/n
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=h:
        raise SystemExit('ERROR: Missing or modified file: '+n)
actual={str(x.relative_to(base)) for x in base.rglob('*') if x.is_file() and x.name!='SHA256_MANIFEST.json' and '__pycache__' not in x.parts and '.pytest_cache' not in x.parts}
if actual!=set(data['files']):raise SystemExit('ERROR: Manifest file list does not match source tree')
print('verified',len(data['files']),'files; unsigned SHA-256 integrity only')
