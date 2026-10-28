"""Reproducible local model workflow without any C++ or AI execution."""
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'studio'))
from server import Studio
s=Studio()
p=s.flow.create('Workflow demo','Verify a real Axiom finite model before any implementation is considered',
                'cpp_project/ledger.ax','cpp_project/project.json')
p=s.flow.verify_spec(p['id'])
a=s.flow.audit(p['id'])
print(json.dumps({'project_id':p['id'],'status':p['status'],'checks':[
 {'action':step['action'],'returncode':step['returncode'],'outcome':step.get('outcome')}
 for step in p['last_verification']['steps']], 'audit':a,
 'production_release_enabled':False},indent=2,ensure_ascii=False))
