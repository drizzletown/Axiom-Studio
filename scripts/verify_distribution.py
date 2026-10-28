#!/usr/bin/env python3
"""Verify exact release file hashes; no remote calls or native execution."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def verify():
    metadata=json.loads((ROOT/'SHA256_MANIFEST.json').read_text('utf-8'))
    files=metadata['files']
    bad=[]
    for rel,expected in files.items():
        p=ROOT/rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts or not p.is_file() or p.is_symlink():
            bad.append(rel+': missing/unsafe')
            continue
        actual=hashlib.sha256(p.read_bytes()).hexdigest()
        if actual!=expected:bad.append(rel+': hash mismatch')
    print(json.dumps({'schema':'ax-studio-file-verification/1.0','files_checked':len(files),
                      'failed':len(bad),'errors':bad[:25], 'verified':not bad},ensure_ascii=False,indent=2))
    return 0 if not bad else 2
if __name__=='__main__':raise SystemExit(verify())
