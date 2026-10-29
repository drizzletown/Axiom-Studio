"""Axiom Studio 1.0 - authoritative local production cockpit.

A read-only coordination layer over the existing workflow/evidence engines. It never
approves candidates or treats a historical check as current release authorization.
"""
from __future__ import annotations
from datetime import datetime, timezone
import shutil
import sys
from pathlib import Path

STAGES=(
    ('spec', '规格与模型检查', 'safe_model'),
    ('contract', '需求-性质契约', 'human_review'),
    ('implementation', '构造候选与方案比较', 'ai_or_human'),
    ('verification', '独立实现验证', 'trusted_local'),
    ('decision', '历史测试级裁决', 'human_review'),
    ('evolution', '变更影响与重新验证', 'human_review'),
)

class Cockpit:
    def __init__(self, studio):
        self.studio=studio

    def _for_project(self, p, orders):
        pid=p['id']
        assessment=self.studio.production.overview(pid)
        audit=self.studio.flow.audit(pid)
        current_orders=[o for o in orders if o.get('manifest')==p.get('manifest')]
        current_orders.sort(key=lambda o:o.get('created',0),reverse=True)
        current_order=current_orders[0] if current_orders else None
        current=p['effective_status']
        audit_ok=bool(audit.get('chain_valid'))
        blockers=assessment.get('blockers',[])
        model_ok=bool(p.get('last_verification') and p['last_verification'].get('passed')) and not p['stale'] and audit_ok
        contract=assessment.get('contract')
        contract_ok=model_ok and bool(contract) and not any(
            b=='PRODUCTION_CONTRACT_STALE' or b.startswith('REQUIREMENT_NOT_MODEL_SUPPORTED:') for b in blockers)
        # A completed test-only decision is a historical checkpoint, never a live release.
        test_accepted=bool(current=='accepted_test_only' and contract_ok and p.get('decision') and audit_ok)
        impl_ok=contract_ok and (test_accepted or bool(current_order and current_order.get('current') and current_order['state'] in
                     ('reviewed','applied','validating','passed','blocked')))
        independent_ok=impl_ok and (test_accepted or bool(current_order and current_order.get('current') and current_order['state']=='passed'))
        statuses=[model_ok, contract_ok, impl_ok, independent_ok, test_accepted, False]
        steps=[]
        for (sid,label,owner),done in zip(STAGES,statuses):
            state='passed' if done else 'pending'
            if (sid=='spec' and current in ('spec_blocked','blocked')) or p['stale']:
                state='blocked' if not done else 'passed'
            steps.append({'id':sid,'title':label,'responsibility':owner,'state':state})
        blockers=list(assessment.get('blockers',[]))
        if not audit.get('chain_valid'):blockers.append('WORKFLOW_AUDIT_INVALID')
        if p['stale']:blockers.append('INPUTS_STALE')
        if current_order and not current_order.get('current'):blockers.append('WORK_ORDER_NOT_CURRENT')
        return {'id':pid,'name':p['name'],'goal':p['goal'],'state':current,'stale':bool(p['stale']),
                'manifest':p['manifest'],'steps':steps,'blockers':sorted(set(blockers)),
                'audit_valid':bool(audit.get('chain_valid')),'workorder':{
                    'id':current_order['id'],'state':current_order['state'],
                    'current':current_order.get('current',False)} if current_order else None,
                'tested_only':test_accepted,'production_release_authorized':False}

    def snapshot(self):
        projects=self.studio.flow.list()
        orders=self.studio.workorders.list()
        # Corrupted project state is visible as an error, not silently counted as approved.
        rows=[];failures=[]
        for p in projects:
            try:
                rows.append(self._for_project(p, orders))
            except Exception as ex:
                failures.append({'id':p.get('id','unknown'),'reason':type(ex).__name__+': '+str(ex)[:150]})
                rows.append({'id':p.get('id'), 'name':p.get('name'), 'state':'unknown',
                    'steps':[], 'blockers':['PROJECT_STATUS_UNAVAILABLE'],'audit_valid':False,
                    'production_release_authorized':False,'tested_only':False,'workorder':None})
        try: queue=self.studio.launchpad.queue()
        except Exception as ex:
            failures.append({'id':'task-queue','reason':type(ex).__name__+': '+str(ex)[:150]})
            queue={'items':[], 'counts':{'attention':0,'total':0}}
        return {'schema':'ax-studio-cockpit/1.0','version':'1.0.0',
                'as_of':datetime.now(timezone.utc).isoformat(),
                'counts':{'total':len(rows), 'model_verified':sum(bool(x['steps']) and x['steps'][0]['state']=='passed' for x in rows),
                          'awaiting_human':sum(x['category']=='human' for x in queue['items']),
                          'blocked_or_stale':sum(bool(x['blockers']) or x['state'] in ('blocked','stale','spec_blocked','unknown') for x in rows),
                          'tested_only':sum(x['tested_only'] for x in rows),
                          'production_release_authorized':0},
                'projects':rows, 'next_actions':queue['items'],
                'recent_orders':[{'id':o['id'],'state':o['state'],'target':o['target'],
                                  'current':o.get('current',False)} for o in orders[:10]],
                'errors':failures,
                'assurance':'bounded models / trusted-local tested C++; production authorization disabled'}

    def doctor(self):
        s=self.studio
        info={'schema':'ax-studio-doctor/1.0','version':'1.0.0','studio_version':'1.5.0',
              'python':sys.version.split()[0],
              'compilers':{'g++':shutil.which('g++'),'clang++':shutil.which('clang++')},
              'evidence_path':str(s.flow.evidence_root) if hasattr(s.flow,'evidence_root') else 'managed',
              'model_engine_present':(Path(s.flow.engine)/'src'/'axiom').is_dir(),
              'protected_policy':True,'native_run_requires_consent':True,
              'sandbox_guaranteed':False,'production_release_authorized':False}
        return info
