#!/usr/bin/env python3
"""Axiom Studio 1.1 clean, offline release smoke test.

Runs a real finite-model verification in an isolated temporary workspace; it NEVER
runs a native executable, calls an AI provider or modifies an existing workspace.
"""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
import server

def main():
    start=time.monotonic()
    checks={}
    with tempfile.TemporaryDirectory(prefix='axiom-release-') as temp:
        t=Path(temp)
        try:
            workspace=t/'workspace'
            workspace.mkdir()
            (workspace/'toggle.ax').write_bytes((ROOT/'studio/templates/model-toggle/toggle.ax').read_bytes())
            server.ROOT=t
            server.WORKSPACE=workspace
            server.EVIDENCE=t/'.studio-data'/'evidence'
            studio=server.Studio()
            try:
                empty=studio.cockpit.snapshot()
                checks['empty_dashboard']=empty['counts']['total']==0 and empty['counts']['production_release_authorized']==0
                p=studio.flow.create('Release smoke','使用真实有限模型验证测试级工作流','toggle.ax')
                before=studio.cockpit.snapshot()['projects'][0]
                checks['project_created']=before['steps'][0]['state']=='pending'
                studio.flow.verify_spec(p['id'])
                after=studio.cockpit.snapshot()['projects'][0]
                checks['model_verified']=after['steps'][0]['state']=='passed'
                checks['contract_requires_human']=after['steps'][1]['state']=='pending'
                checks['no_unearned_release']=after['production_release_authorized'] is False
                checks['audit_valid']=after['audit_valid'] is True
                checks['read_only_cockpit']=not list((workspace).glob('*.cpp'))
                checks['doctor_fail_closed']=not studio.cockpit.doctor()['sandbox_guaranteed']
                journey=studio.journey.snapshot()
                checks['intent_first_api']=journey['schema']=='ax-studio-journey/1.1'
                checks['production_release_disabled']=journey['production_release_authorized'] is False
                checks['honest_spec_scope']='不会自动' in journey['important_notice']
                created=studio.journey.start('model-ledger','自检软件项目','软件必须遵守状态守恒规则')
                checks['no_training_start']=created['goal_status']=='recorded_unverified'
                new_pid=created['project']['id']
                new_row=next(r for r in studio.journey.snapshot()['projects'] if r['id']==new_pid)
                checks['next_step_guidance']=new_row['next']['id']=='verify' and not new_row['model_checked']
                checks['no_implicit_native_execution']=not studio.recent()
            finally:studio.executor.shutdown(wait=False,cancel_futures=True)
        except Exception as e:
            checks['unexpected_exception']=type(e).__name__+': '+str(e)[:250]
    result={'schema':'ax-studio-release-selftest/1.0','version':'2.0.0',
            'checks':checks,'passed':sum(v is True for v in checks.values()),
            'total':len(checks),'all_passed':all(v is True for v in checks.values()),
            'elapsed_seconds':round(time.monotonic()-start,3),
            'scope':'trusted local finite model; no native C++, no AI, no production release'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['all_passed'] else 2

if __name__=='__main__':raise SystemExit(main())
