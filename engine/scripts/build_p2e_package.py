from pathlib import Path
import hashlib,json,zipfile,shutil
ROOT=Path(__file__).resolve().parents[1]
OUT=Path('/mnt/data/Axiom_P2_第五批完整源码与验收资料_20261025.zip')
DOC=Path('/mnt/data/Axiom_P2_第五批实施与验收报告_V0.5_20261025.docx')
ignore_dirs={'.axiom','.pytest_cache','__pycache__','.git','.tox','venv','.venv','build','dist'}
ignore_names={'manifest.json','test_verbose.log','pytest_p2e_full.exit','pytest_p2e.txt'}
files=[]
for file in ROOT.rglob('*'):
    if not file.is_file() or file.is_symlink() or any(x in ignore_dirs for x in file.relative_to(ROOT).parts):continue
    if file.name in ignore_names or file.name.endswith('.pyc'):continue
    files.append(file)
manifest={'package':'Axiom P2e 0.7.0','theory_baseline':'Axiom 0.2',
          'high_level_design':'Axiom 1.0','file_count':len(files),
          'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
(ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
with zipfile.ZipFile(OUT,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as z:
    for p in sorted(files)+[ROOT/'manifest.json']:
        z.write(p,'axiom-p2e/'+str(p.relative_to(ROOT)))
shutil.copy2(ROOT/'docs'/'Axiom_P2_第五批实施与验收报告_V0.5_20261025.docx',DOC)
print('files',len(files),'zip',OUT,'size',OUT.stat().st_size,'report',DOC.stat().st_size)
