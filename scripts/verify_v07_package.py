#!/usr/bin/env python3
"""Verify the V0.7 distribution after unpacking; no network or native execution."""
import hashlib, json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'SHA256_MANIFEST.json').read_text('utf-8'))
assert manifest['schema']=='ax-studio-package/0.7'
for entry in manifest['files']:
    data=(root/entry['path']).read_bytes()
    assert len(data)==entry['size'],entry['path']
    assert hashlib.sha256(data).hexdigest()==entry['sha256'],entry['path']
print(json.dumps({'ok':True,'files_verified':len(manifest['files']),'scope':'Axiom Studio source distribution'},ensure_ascii=False))
