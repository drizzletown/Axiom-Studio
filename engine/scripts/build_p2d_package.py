"""Deterministic manifest and zip; exclude workspaces, keys, caches and bytecode."""
from pathlib import Path
import zipfile,json,hashlib
root=Path(__file__).resolve().parents[1]
output=Path('/mnt/data/Axiom_P2_第四批完整源码与验收资料_20261025.zip')
folders=['src','tests','cpp','docs','examples','scripts','reports']
files=[root/'README.md',root/'pyproject.toml']
for folder in folders:
    files.extend(p for p in (root/folder).rglob('*') if p.is_file() and not any(x in p.parts for x in ('__pycache__','.pytest_cache')) and p.suffix not in ('.pyc','.pyo') and not p.is_symlink())
files=sorted(set(files))
assert all(not any(x in p.suffixes for x in ('.pem','.key','.sqlite3')) for p in files)
manifest={'artifact':'Axiom P2d fourth batch','version':'0.6.0','algorithm':'sha256',
          'files':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
files.append(root/'manifest.json')
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(files):
        arcname=str(Path(root.name)/p.relative_to(root))
        z.write(p,arcname)
print(output,'files:',len(files),'bytes:',output.stat().st_size)
