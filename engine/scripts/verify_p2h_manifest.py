"""Verifies packaged file checksums (integrity, not authenticity)."""
from pathlib import Path
import hashlib,json,sys
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'manifest.json').read_text())
assert manifest['schema']=='ax-p2h-files/0.1'
listed=manifest['files']
actual={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file() and p.name!='manifest.json'
        and not any(v in p.parts for v in ('__pycache__','.pytest_cache'))}
assert actual==listed,f'missing/changed/extra files: {set(actual)^set(listed)}'
print('OK:',len(listed),'file SHA-256 digests match')
