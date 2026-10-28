"""Verify SHA-256 manifest from extracted bundle; never modify files."""
import hashlib
import json
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'sha256_manifest.json').read_text(encoding='utf8'))
errors=[]
for rel,h in manifest['files'].items():
    path=(root/rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():errors.append(rel+': MISSING');continue
    current=hashlib.sha256(path.read_bytes()).hexdigest()
    if current!=h:errors.append(rel+': CHANGED')
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and not any(part in ('__pycache__','.pytest_cache','.ax-p2f') for part in p.parts) and p.name!='sha256_manifest.json'}
extra=actual-set(manifest['files'])
errors.extend(sorted('EXTRA '+rel for rel in extra))
print(json.dumps({'expected':len(manifest['files']),'verified':len(manifest['files'])-len(errors),
                  'status':'OK' if not errors else 'FAIL','errors':errors[:20]},ensure_ascii=False,indent=2))
sys.exit(bool(errors))
