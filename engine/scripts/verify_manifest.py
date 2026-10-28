from pathlib import Path
import hashlib
import json

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
for name,required in manifest['files'].items():
    p=root/name
    assert p.is_file() and not p.is_symlink(), f'missing/nonregular: {name}'
    actual=hashlib.sha256(p.read_bytes()).hexdigest()
    assert actual==required, f'mismatch: {name}'
print(f"Verified {len(manifest['files'])} delivery files")
