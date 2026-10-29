"""Axiom Studio V0.4 - intent-to-evidence production contracts.

A *production contract* makes traceability and authorization enforceable, not
merely a dashboard. Requirements are linked syntactically to properties of a
pinned Axiom IR; this does NOT establish that prose is implied by the property.
The only issuable passport is a cpp-tested-prototype snapshot, never a release.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

from orchestrator import FlowConflict, FlowError, canonical, digest

SCHEMA='ax-production/0.4'
VALID_KINDS={'invariant','unverified'}


def _load_ax(engine:Path, source:str)->dict:
    src=str(engine/'src')
    if src not in sys.path:sys.path.insert(0,src)
    from axiom.lang import parse, validate
    ir=parse(source)
    validate(ir)
    return ir


def _sha(value:Any)->str:
    return 'sha256:'+digest(canonical(value))


class Production:
    def __init__(self, flow):
        self.flow=flow
        with self.flow.lock,self.flow._connect() as cx:
            cx.executescript('''
                CREATE TABLE IF NOT EXISTS production_contracts(
                  project_id TEXT PRIMARY KEY, body TEXT NOT NULL,
                  body_digest TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS production_passports(
                  passport_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                  body TEXT NOT NULL, body_digest TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS passports_project ON production_passports(project_id,created);
            ''')

    def _model(self,p:dict)->dict:
        return _load_ax(self.flow.engine,self.flow._file(p['spec'],'.ax').read_text('utf-8'))

    def _read_contract(self,cx,pid):
        row=cx.execute('SELECT * FROM production_contracts WHERE project_id=?',(pid,)).fetchone()
        if not row:return None
        body=json.loads(row['body'])
        if _sha(body)!=row['body_digest']:
            raise FlowConflict('生产契约完整性检查失败，拒绝信任本地记录')
        return {'body':body,'digest':row['body_digest'],'created':row['created']}

    def draft(self,pid):
        """Suggested *uncommitted* requirement skeleton extracted from AST."""
        p=self.flow.get(pid)
        ir=self._model(p)
        return {'schema':SCHEMA,'project_id':pid,'spec':p['spec'],
                'suggested':[{'id':'REQ-'+str(i+1).zfill(3),'text':'请确认性质 '+v['name']+' 对应的需求含义',
                    'kind':'invariant','property':v['name']}
                    for i,v in enumerate(ir['properties'])],
                'warning':'这里只验证性质标识及当前 Axiom 模型；自然语言需求与性质的语义等价须人工确认。'}

    def freeze(self,pid,requirements,expected_baseline=None,source_plan_digest=None):
        if not isinstance(requirements,list) or not (1<=len(requirements)<=100):
            raise FlowError('需给出 1–100 项明确需求')
        with self.flow.lock,self.flow._connect() as cx:
            p=self.flow._row(cx,pid)
            self.flow._assert_not_stale(p)
            if self._read_contract(cx,pid):raise FlowConflict('生产契约已冻结。修改需求须建立新的演化项目。')
            baseline=json.loads(p['baseline'])
            if expected_baseline is not None and expected_baseline!=baseline:
                raise FlowConflict('规格摘要已变化，请重新取得需求草稿')
            ir=self._model(p)
            props={v['name']:v for v in ir['properties']}
            names=set(); normalized=[]
            for r in requirements:
                if not isinstance(r,dict):raise FlowError('需求项须为对象')
                rid=r.get('id');statement=r.get('text');kind=r.get('kind');property_name=r.get('property')
                if not isinstance(rid,str) or not rid.startswith('REQ-') or len(rid)>55 or not rid[4:].replace('-','').replace('_','').isalnum():
                    raise FlowError('需求 ID 必须是 REQ- 开头的明确标识')
                if rid in names:raise FlowError('需求 ID 重复')
                names.add(rid)
                if not isinstance(statement,str) or not (8<=len(statement.strip())<=1500):
                    raise FlowError('需求陈述需为 8–1500 字符')
                if kind not in VALID_KINDS:raise FlowError('未知需求验证类型')
                if kind=='invariant':
                    if not isinstance(property_name,str) or property_name not in props:
                        raise FlowError('形式性质不存在于当前 Axiom 规格')
                    bound={'name':property_name,'expr_digest':_sha(props[property_name]['expr'])}
                else:
                    if property_name not in (None,''):raise FlowError('未验证需求不能伪造形式性质映射')
                    bound=None
                normalized.append({'id':rid,'text':statement.strip(),'kind':kind,'binding':bound})
            body={'schema':SCHEMA,'project_id':pid,'project_revision':p['revision'],
                  'baseline':baseline,'model_digest':_sha(ir),'requirements':normalized,
                  'human_review_source':source_plan_digest,
                  'assurance_policy':{'issue':'cpp-tested-prototype only','production_release':False,
                      'all_requirements_must_be_model_bound':True,'human_decision_required':True,
                      'live_cpp_gate_required':True},
                  'limitations':'Binding of natural-language requirements to Axiom property names is human-reviewed traceability, not a proof of equivalence.'}
            body_digest=_sha(body)
            cx.execute('INSERT INTO production_contracts VALUES(?,?,?,?)',
                 (pid,canonical(body).decode('utf-8'),body_digest,time.time()))
            self.flow._event(cx,pid,'production_contract_frozen',
                 {'contract_digest':body_digest,'requirement_ids':[v['id'] for v in normalized],
                  'unverified_count':sum(v['kind']=='unverified' for v in normalized),
                  'human_review_source':source_plan_digest})
            return {'body':body,'digest':body_digest}

    def _assess(self,p,record,ir,audit):
        blocks=[];links=[]
        if p['stale']:blocks.append('SPEC_OR_MANIFEST_STALE')
        if not audit['chain_valid']:blocks.append('PROCESS_AUDIT_CHAIN_INVALID')
        if record is None:
            blocks.append('PRODUCTION_CONTRACT_MISSING')
        else:
            body=record['body']
            if body['baseline']!=p['baseline'] or body['model_digest']!=_sha(ir):
                blocks.append('PRODUCTION_CONTRACT_STALE')
            props={v['name']:_sha(v['expr']) for v in ir['properties']}
            for req in body['requirements']:
                evidence='unverified'
                binding=req.get('binding')
                if req['kind']=='invariant' and binding and props.get(binding['name'])==binding['expr_digest']:
                    evidence='property-linked'
                if evidence!='property-linked':blocks.append('REQUIREMENT_NOT_MODEL_SUPPORTED:'+req['id'])
                links.append({'requirement_id':req['id'],'kind':req['kind'],
                              'property':binding['name'] if binding else None,
                              'status':evidence})
        if p['effective_status'] not in ('spec_ready','candidate_review','candidate_apply',
            'candidate_validate','decision_pending','blocked','accepted_test_only') or \
            not p['last_verification'] or not p['last_verification'].get('passed'):
            blocks.append('MODEL_GATE_REQUIRED')
        if p['effective_status']!='accepted_test_only' or not p['decision']:
            blocks.append('HUMAN_ACCEPTANCE_AND_CPP_GATE_REQUIRED')
        # 'ready_to_issue' is provisional. issue_passport() rechecks the live gate.
        return {'schema':SCHEMA,'project_id':p['id'],'contract_digest':record['digest'] if record else None,
                'links':links,'blockers':sorted(set(blocks)),'eligible_for_live_recheck':not blocks,
                'assurance':'cpp-tested-prototype; no production release'}

    def overview(self,pid):
        p=self.flow.get(pid)
        with self.flow.lock,self.flow._connect() as cx:
            self.flow._row(cx,pid)
            record=self._read_contract(cx,pid)
        try:ir=self._model(p)
        except Exception as exc:
            return {'project_id':pid,'blockers':['SPEC_MODEL_NOT_PARSEABLE'],
                    'error':str(exc)[:200],'contract_digest':record['digest'] if record else None}
        result=self._assess(p,record,ir,self.flow.audit(pid))
        result['contract']=record
        return result

    def graph(self,pid):
        p=self.flow.get(pid);ir=self._model(p);assessment=self.overview(pid)
        nodes=[{'id':'goal','type':'intent','label':p['goal'][:130]},
               {'id':'spec','type':'model','label':p['spec']}]
        edges=[{'from':'goal','to':'spec','kind':'refined_by'}]
        for a in ir['actions']:
            nodes.append({'id':'action:'+a['name'],'type':'action','label':a['name']})
            edges.append({'from':'spec','to':'action:'+a['name'],'kind':'declares'})
        for prop in ir['properties']:
            nodes.append({'id':'property:'+prop['name'],'type':'property','label':prop['name']})
            edges.append({'from':'spec','to':'property:'+prop['name'],'kind':'declares'})
        for link in assessment.get('links',[]):
            nodes.append({'id':'requirement:'+link['requirement_id'],'type':'requirement','label':link['requirement_id'],
                          'status':link['status']})
            edges.append({'from':'goal','to':'requirement:'+link['requirement_id'],'kind':'decomposes'})
            if link['property']:
                edges.append({'from':'requirement:'+link['requirement_id'],
                              'to':'property:'+link['property'],'kind':'mapped_by_human'})
        if p['candidate_id']:
            nodes.append({'id':'candidate','type':'implementation','label':p['candidate_id']})
            edges.append({'from':'spec','to':'candidate','kind':'implementation_candidate'})
        if p['last_verification']:
            nodes.append({'id':'model-evidence','type':'evidence','label':'Bounded model evidence'})
            edges.append({'from':'spec','to':'model-evidence','kind':'checked_by'})
        if p['decision']:
            nodes.append({'id':'decision','type':'decision','label':'AcceptedForPrototypeOnly'})
            edges.extend([{'from':'candidate','to':'decision','kind':'reviewed_for'},
                          {'from':'model-evidence','to':'decision','kind':'informs'}])
        return {'schema':SCHEMA,'nodes':nodes,'edges':edges,'blockers':assessment.get('blockers',[])}

    def task_packet(self,pid):
        p=self.flow.get(pid);ir=self._model(p);a=self.overview(pid)
        if not a.get('contract'):raise FlowConflict('必须先由人确认并冻结需求—性质映射，才能生成构造任务')
        if 'PRODUCTION_CONTRACT_STALE' in a['blockers'] or p['stale']:
            raise FlowConflict('规格或生产契约已失效，不能签发构造任务')
        contract=a['contract']
        packet={'schema':'ax-production-task/0.4','project_id':pid,
                'contract_digest':contract['digest'],'baseline':p['baseline'],
                'requirements':contract['body']['requirements'],
                'specification':p['spec'],
                'actions':[{'name':v['name'],'inputs':v['inputs'],'output':v['output']} for v in ir['actions']],
                'properties':[v['name'] for v in ir['properties']],
                'manifest':p['manifest'],
                'phases':['AI candidate in staging','human review','apply approved digest',
                          'independent model and implementation validation','evidence Gate','human decision'],
                'prohibited_changes':['behavioral specification','requirements and contracts','test sources',
                                      'verification tools','Gate policy','evidence store'],
                'scope':'proposal only; no AI approval, no automatic application or production release'}
        return {'packet':packet,'digest':_sha(packet)}

    def issue_passport(self,pid,confirmation,expected_contract_digest):
        if confirmation!='issue_test_only':raise FlowError('必须确认仅签发测试级生产护照')
        with self.flow.lock,self.flow._connect() as cx:
            p=self.flow._public(self.flow._row(cx,pid))
            record=self._read_contract(cx,pid)
            if not record or record['digest']!=expected_contract_digest:
                raise FlowConflict('契约摘要不匹配或尚未冻结')
            ir=self._model(p)
            a=self._assess(p,record,ir,self.flow.audit(pid))
            if a['blockers']:raise FlowConflict('当前不满足护照签发要求：'+','.join(a['blockers']))
            candidate=self.flow.proposals.get(p['candidate_id'])
            if candidate['status']!='verified' or not candidate['current'] or \
                candidate['code_sha256']!=p['decision']['code_sha256']:
                raise FlowConflict('当前候选和原始裁决不一致')
            validation=candidate.get('validation') or {}
            checks=validation.get('checks') or []
            if not validation.get('passed') or {v['step'] for v in checks}!= \
                {'spec-model','spec-gate','cpp-full','cpp-gate'}:
                raise FlowConflict('独立验证链不完整')
            if any(v['returncode']!=0 for v in checks):raise FlowConflict('独立检查曾失败')
            if any(v['outcome']!='Approved' for v in checks if v['step'].endswith('gate')):
                raise FlowConflict('准入证据曾被拒绝')
            live_evidence=self.flow.db.parent/'candidate-evidence'/p['candidate_id']
            gate=self.flow._cli(live_evidence,'cpp-project-gate',self.flow._file(p['manifest'],'.json'),timeout=30)
            if gate['returncode']!=0 or gate.get('outcome')!='Approved':
                raise FlowConflict('实时 C++ Gate 没有通过')
            # Re-read after running external process. No approval if anything changed.
            latest=self.flow._public(self.flow._row(cx,pid))
            if latest['stale'] or latest['status']!='accepted_test_only' or \
                not self.flow.proposals.get(p['candidate_id'])['current']:
                raise FlowConflict('实时 Gate 后依赖发生变化')
            chain_tip=cx.execute('SELECT entry_hash FROM events WHERE project_id=? ORDER BY row_id DESC LIMIT 1',(pid,)).fetchone()
            body={'schema':'ax-production-passport/0.4','project_id':pid,'revision':p['revision'],
                  'contract_digest':record['digest'],'baseline':p['baseline'],
                  'requirement_links':a['links'],'candidate_id':p['candidate_id'],
                  'candidate_sha256':candidate['code_sha256'],
                  'validation_steps':[{'step':v['step'],'outcome':v['outcome'],'returncode':v['returncode']} for v in checks],
                  'gate':'Approved','process_audit_tip':chain_tip['entry_hash'] if chain_tip else None,
                  'decision':p['decision'],'issued_at':time.time(),
                  'scope':'cpp-tested-prototype','production_release':False,
                  'limitations':'Finite-model plus declared tests only; no general refinement proof, no production approval.'}
            body_digest=_sha(body);passport_id='passport-'+body_digest[7:23]
            cx.execute('INSERT INTO production_passports VALUES(?,?,?,?,?)',
                       (passport_id,pid,canonical(body).decode('utf-8'),body_digest,body['issued_at']))
            self.flow._event(cx,pid,'prototype_passport_issued',{'passport_id':passport_id,'digest':body_digest})
            return {'id':passport_id,'digest':body_digest,'passport':body}

    def passports(self,pid):
        p=self.flow.get(pid)
        with self.flow.lock,self.flow._connect() as cx:
            self.flow._row(cx,pid)
            rows=cx.execute('SELECT * FROM production_passports WHERE project_id=? ORDER BY created DESC LIMIT 50',(pid,)).fetchall()
            contract=self._read_contract(cx,pid)
        try:
            proposal=self.flow.proposals.get(p['candidate_id']) if p.get('candidate_id') else None
        except (LookupError,ValueError,FlowError):
            proposal=None
        chain_ok=self.flow.audit(pid)['chain_valid']
        result=[]
        for r in rows:
            body=json.loads(r['body']);integrity=_sha(body)==r['body_digest']
            fresh=(integrity and contract is not None and contract['digest']==body['contract_digest']
                   and p['baseline']==body['baseline'] and not p['stale']
                   and p['candidate_id']==body['candidate_id'] and chain_ok
                   and proposal is not None and proposal.get('current')
                   and proposal.get('status')=='verified'
                   and proposal.get('code_sha256')==body['candidate_sha256']
                   and p['decision'] and p['decision']['code_sha256']==body['candidate_sha256'])
            result.append({'id':r['passport_id'],'digest':r['body_digest'],'body':body,
                'record_integrity':integrity,'snapshot_matches_current':bool(fresh),
                'live_gate_rechecked':False})
        return {'project_id':pid,'passports':result,
                'warning':'历史快照仅表示签发当时的测试级证据；查看历史不进行实时 Gate 验证。'}
