"""Immutable content-addressed artifacts, append-only run records, assessments and gates.

P0 scope: local trust boundary only. Filesystem attackers could tamper with SQLite;
strong process isolation, digital signatures and authorization are P1+ work.
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from .lang import canonical_bytes, digest
from .checker import obligations
from . import checker, lang

POLICY={"policy_id":"AX-P0-SAFE-DEFAULT","policy_version":"1",
        "model":{"required_assurance":"Bounded","requires_exhaustion":True},
        "cpp":{"requires_implementation_evidence":True,"requires_binding":True}}

def _now():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())

def _id(prefix):return prefix+'-'+uuid.uuid4().hex[:20]

def toolchain_digest():
    """A P0 toolchain fingerprint, not a cryptographic attestation."""
    from importlib.metadata import version
    b=checker.__file__ and Path(checker.__file__).read_bytes()
    l=lang.__file__ and Path(lang.__file__).read_bytes()
    metadata={"python":sys.version.split()[0],"lark":version('lark'),"semantics":"ax-sem/0.1"}
    return digest(b+l+canonical_bytes(metadata))


class Workspace:
    def __init__(self,root):
        self.root=Path(root)
        self.objects=self.root/'objects'
        self.db_path=self.root/'index.sqlite3'
        self.objects.mkdir(parents=True,exist_ok=True)
        self._init()
    def _db(self):
        db=sqlite3.connect(self.db_path,timeout=10)
        db.row_factory=sqlite3.Row
        return db
    def _init(self):
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS runs (
               run_id TEXT PRIMARY KEY, spec_digest TEXT NOT NULL,
               evidence_digest TEXT NOT NULL, outcome TEXT NOT NULL,
               created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assessments (
               assessment_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
               target_spec_digest TEXT NOT NULL, freshness TEXT NOT NULL,
               reason TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS gates (
               gate_id TEXT PRIMARY KEY, target TEXT NOT NULL,
               candidate_digest TEXT, spec_digest TEXT NOT NULL,
               policy_digest TEXT NOT NULL, decision TEXT NOT NULL,
               details_digest TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_runs_spec ON runs(spec_digest);
            ''')
    def object_path(self,h):
        if not isinstance(h,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', h):
            raise ValueError('invalid content-addressed object digest')
        return self.objects/h.split(':',1)[1]
    def put_bytes(self,raw:bytes)->str:
        h=digest(raw)
        name=self.object_path(h)
        if not name.exists():
            # Race-safe and never overwrite existing immutable objects.
            try:
                with open(name,'xb') as f:
                    f.write(raw);f.flush();os.fsync(f.fileno())
            except FileExistsError: pass
        if digest(name.read_bytes())!=h: raise ValueError('object corruption')
        return h
    def put(self,obj): return self.put_bytes(canonical_bytes(obj))
    def get(self,h):
        data=self.object_path(h).read_bytes()
        if digest(data)!=h: raise ValueError('content-addressed object mismatch')
        return json.loads(data)
    def record(self,ir,report):
        # A result passed through the Python API is not an authority. At minimum
        # independently re-run the finite checker before admitting a Bounded
        # assertion to the evidence store. This guards against accidental or
        # trivially fabricated reports, not against a hostile local process.
        if report.get('outcome') == 'Bounded':
            scoped=report.get('scope',{})
            from .checker import verify
            max_states=scoped.get('max_states',50000)
            max_transitions=scoped.get('max_transitions',250000)
            timeout=scoped.get('timeout_seconds',30)
            if not (type(max_states) is int and 1<=max_states<=500000 and
                    type(max_transitions) is int and 1<=max_transitions<=1000000 and
                    type(timeout) in (int,float) and 0<timeout<=120):
                raise ValueError('invalid bounded report scope')
            replay=verify(ir,max_states=max_states,max_transitions=max_transitions,timeout_s=timeout)
            if canonical_bytes(replay)!=canonical_bytes(report):
                raise ValueError('bounded report does not match checker replay')
        ir_digest=self.put(ir)
        run_id=_id('run')
        log={"run_id":run_id,"ir_digest":ir_digest,"report":report,"at":_now()}
        log_digest=self.put(log)
        evid={"evidence_id":_id('evidence'),"run_id":run_id,
              "obligation_ids":[o['id'] for o in obligations(ir)],
              "subject":"abstract-model","spec_digest":ir_digest,
              "subject_digest":ir_digest,"semantics_version":ir['semantics_version'],
              "binding_digest":None,"assumptions_digest":self.put({"assumptions":["finite domains","atomic synchronous action boundaries"]}),
              "outcome":report['outcome'],
              "assurance_kind":report['outcome'] if report['outcome'] in ('Bounded','Proved','Tested','Observed') else 'None',
              "scope":report.get('scope',{}),"assumptions":["finite domains","atomic synchronous action boundaries"],
              "tool_id":"axiom-p0-enumerator","tool_version":"0.1.0",
              "tool_digest":toolchain_digest(),
              "witness_digest":log_digest,"produced_at":_now()}
        evid_digest=self.put(evid)
        with self._db() as db:
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',(run_id,ir_digest,evid_digest,report['outcome'],_now()))
        return {"run_id":run_id,"spec_digest":ir_digest,"evidence_digest":evid_digest,
                "report_digest":log_digest,"outcome":report['outcome']}
    def runs(self):
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM runs ORDER BY created_at,run_id')]
    def assess(self,run_id,target_spec_digest):
        with self._db() as db:
            row=db.execute('SELECT * FROM runs WHERE run_id=?',(run_id,)).fetchone()
        if row is None: raise ValueError('Unknown run')
        ev=self.get(row['evidence_digest'])
        exact=(ev['spec_digest']==target_spec_digest and ev['subject_digest']==target_spec_digest
               and ev['semantics_version']=='ax-sem/0.1'
               and ev.get('tool_digest')==toolchain_digest())
        valid=(ev['outcome']=='Bounded' and ev['scope'].get('finite_reachable_exhaustion') is True)
        freshness='Current' if exact and valid else 'Stale' if not exact else 'Revalidate'
        reason='exact-semantic-match' if exact and valid else 'changed-semantics-or-context' if not exact else 'no-qualifying-evidence'
        item={"assessment_id":_id('assessment'),"run_id":run_id,
              "target_spec_digest":target_spec_digest,"freshness":freshness,
              "reason":reason,"created_at":_now()}
        with self._db() as db:
            db.execute('INSERT INTO assessments VALUES (?,?,?,?,?,?)',tuple(item[k] for k in (
                'assessment_id','run_id','target_spec_digest','freshness','reason','created_at')))
        return item
    def gate(self,ir,target='cpp',candidate_digest=None):
        ir_digest=self.put(ir); p_digest=self.put(POLICY)
        eligible=[]
        for r in self.runs():
            a=self.assess(r['run_id'],ir_digest)
            if a['freshness']=='Current':eligible.append(r)
        requirements=[o['id'] for o in obligations(ir)]
        satisfied=set()
        for r in eligible:
            ev=self.get(r['evidence_digest'])
            if ev['subject']=='abstract-model' and ev['assurance_kind']=='Bounded':
                satisfied.update(ev['obligation_ids'])
        reasons=[]
        if any(o not in satisfied for o in requirements):reasons.append('MISSING_CURRENT_MODEL_EVIDENCE')
        if target=='cpp':
            if not candidate_digest:reasons.append('MISSING_CANDIDATE_DIGEST')
            reasons.append('MISSING_CPP_BINDING_AND_IMPLEMENTATION_EVIDENCE')
        decision='Blocked' if reasons else 'Approved'
        details={"gate_id":_id('gate'),"target":target,"candidate_digest":candidate_digest,
                 "spec_digest":ir_digest,"policy_digest":p_digest,"decision":decision,
                 "reasons":reasons,"satisfied_model_obligations":sorted(satisfied),
                 "required_model_obligations":requirements,"stage":"P0","created_at":_now()}
        details_digest=self.put(details)
        with self._db() as db:
            db.execute('INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)',(
              details['gate_id'],target,candidate_digest,ir_digest,p_digest,decision,details_digest,_now()))
        return details

    # --- P1 extension: implementation-level test runs ---
    def _cpp_init(self):
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS cpp_runs (
              run_id TEXT PRIMARY KEY, spec_digest TEXT NOT NULL,
              source_digest TEXT NOT NULL, binding_digest TEXT NOT NULL,
              config_digest TEXT NOT NULL, evidence_digest TEXT NOT NULL,
              outcome TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_cpp_runs ON cpp_runs(spec_digest,source_digest,binding_digest,config_digest);
            ''')

    def record_cpp(self,ir,report,binaries):
        """Append a P1 run; historical outcome is never rewritten.

        This is a local research tool, not an adversary-resistant provenance service.
        """
        self._cpp_init()
        artifacts={}
        for name,blob in binaries.items():
            artifacts[name]=self.put_bytes(blob)
        if set(artifacts) != {'source','binding','harness','context','normal','sanitized'}:
            # Compile failures may still be recorded, with fewer binaries.
            if not {'source','binding','harness','context'}.issubset(artifacts):
                raise ValueError('missing provenance snapshots')
        for mode in ('normal','sanitized'):
            if mode in artifacts and report['variants'][mode]['binary_digest']!=artifacts[mode]:
                raise ValueError('binary fingerprint mismatch')
        if (report['source_digest']!=artifacts['source'] or
            report['binding_digest']!=artifacts['binding'] or
            report['harness_digest']!=artifacts['harness'] or
            report['config_digest']!=artifacts['context']):
            raise ValueError('provenance snapshot differs from reported digest')
        report_copy={**report,'stored_artifacts':artifacts}
        evidence={'subject':'cpp-executable-test','assurance':'Tested' if report['outcome']=='Tested' else 'None',
                  'run_id':_id('cpp-run'), 'spec_digest':report['model_digest'],
                  'source_digest':report['source_digest'],'binding_digest':report['binding_digest'],
                  'config_digest':report['config_digest'],
                  'binary_digests':{k:artifacts[k] for k in ('normal','sanitized') if k in artifacts},
                  'artifact_digests':artifacts,
                  'scope':report['scope'],'outcome':report['outcome'],
                  'report_digest':self.put(report_copy), 'recorded_at':_now()}
        ev_digest=self.put(evidence)
        with self._db() as db:
            db.execute('INSERT INTO cpp_runs VALUES (?,?,?,?,?,?,?,?)',(
                evidence['run_id'],report['model_digest'],report['source_digest'],
                report['binding_digest'],report['config_digest'],ev_digest,report['outcome'],_now()))
        return {'run_id':evidence['run_id'],'evidence_digest':ev_digest,
                'report_digest':evidence['report_digest'],'outcome':report['outcome'],
                'source_digest':report['source_digest'],'binding_digest':report['binding_digest'],
                'config_digest':report['config_digest'],'binary_digests':evidence['binary_digests'],'artifact_digests':artifacts}

    def cpp_runs(self):
        self._cpp_init()
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM cpp_runs ORDER BY created_at,run_id')]

    def gate_cpp(self,ir,candidate,binding_path,*,compiler='g++',optimization='1'):
        """Local verification gate, independent of user-supplied report/status."""
        from .cpp import load_binding,compiler_context,POLICY_VERSION,RUNNER_VERSION
        self._cpp_init()
        ir_digest=self.put(ir)
        b=load_binding(binding_path,ir)
        src_digest=digest(Path(candidate).read_bytes())
        bind_digest=digest(b)
        config_digest=digest(compiler_context(compiler,optimization))
        reasons=[]; selected=None; assessed=[]
        if self.gate(ir,target='model')['decision']!='Approved':
            reasons.append('MISSING_CURRENT_MODEL_EVIDENCE')
        for row in reversed(self.cpp_runs()):
            if row['spec_digest']!=ir_digest or row['source_digest']!=src_digest or row['binding_digest']!=bind_digest or row['config_digest']!=config_digest:
                continue
            evidence=self.get(row['evidence_digest'])
            report=self.get(evidence['report_digest'])
            ok=(row['outcome']=='Tested' and evidence['outcome']=='Tested' and evidence['assurance']=='Tested'
                and report['outcome']=='Tested' and report['runner_version']==RUNNER_VERSION
                and report['scope']['all_model_reachable_state_input_pairs'] is True
                and report['scope']['tested_pairs']>0
                and report['scope']['each_model_pair_repeated'] is True
                and report['scope']['observed_calls_per_variant']==2*report['scope']['tested_pairs']
                and set(evidence['binary_digests'])=={'normal','sanitized'}
                and all(report['variants'][mode]['binary_digest']==h for mode,h in evidence['binary_digests'].items())
                and evidence['artifact_digests']['source']==src_digest
                and evidence['artifact_digests']['binding']==bind_digest
                and evidence['artifact_digests']['context']==config_digest
                and evidence['artifact_digests']['harness']==report['harness_digest']
                and all(report['variants'][mode]['execution_exit']==0 for mode in ('normal','sanitized')))
            # Ensure all claimed stored binary artifacts exist and their contents match.
            try:
                for h in evidence['artifact_digests'].values():
                    raw=self.object_path(h).read_bytes()
                    if digest(raw)!=h: raise ValueError('binary content mismatch')
            except (OSError,ValueError):ok=False
            assessed.append({'run_id':row['run_id'],'qualifies':ok})
            if ok:
                selected=row['run_id'];break
        if not selected:reasons.append('MISSING_MATCHING_CPP_TEST_EVIDENCE')
        decision='Approved' if not reasons else 'Blocked'
        doc={'gate_id':_id('cpp-gate'),'stage':'P1','target':'cpp-tested-prototype',
             'policy_version':POLICY_VERSION,'decision':decision,'reasons':reasons,
             'spec_digest':ir_digest,'source_digest':src_digest,'binding_digest':bind_digest,
             'config_digest':config_digest,'cpp_evidence_run_id':selected,'assessed':assessed,
             'assurance':'Tested' if decision=='Approved' else 'None',
             'scope_note':'Only finite differential observations and sanitizer check; not a refinement proof, not a production release',
             'created_at':_now()}
        self.put(doc)
        return doc


    # --- P2 experimental per-obligation model evidence reuse ---
    def gate_model_evolved(self, ir):
        """Fail-closed, model-only gate composed from compatible bounded records.

        Existing P0 gate and P1 C++ gate retain their original strict rules.
        Historical model runs must be Bounded, with exhaustive finite coverage,
        a matching checker digest, and snapshots with identical action semantics.
        """
        from .evolution import (POLICY_VERSION as EVOLUTION_POLICY,
                                behavior_digest, model_obligation_fingerprint)
        validate_ir = lang.validate
        validate_ir(ir)
        self.put(ir)
        required = {x['id']: model_obligation_fingerprint(ir, x['id']) for x in obligations(ir)}
        covered = {}
        rejected = []
        for row in reversed(self.runs()):
            try:
                evidence = self.get(row['evidence_digest'])
                old_ir = self.get(evidence['spec_digest'])
                validate_ir(old_ir)
                report = self.get(evidence['witness_digest'])['report']
                valid = (row['spec_digest'] == evidence['spec_digest'] == digest(old_ir)
                         and row['outcome'] == evidence['outcome'] == report['outcome'] == 'Bounded'
                         and evidence.get('subject') == 'abstract-model'
                         and evidence.get('semantics_version') == ir['semantics_version']
                         and evidence.get('tool_digest') == toolchain_digest()
                         and evidence.get('scope',{}).get('finite_reachable_exhaustion') is True
                         and report.get('scope',{}).get('finite_reachable_exhaustion') is True
                         and set(evidence.get('obligation_ids',[])) == {o['id'] for o in obligations(old_ir)}
                         and set(report.get('verified_obligation_ids', [])) == {o['id'] for o in obligations(old_ir)}
                         and behavior_digest(old_ir) == behavior_digest(ir))
                if not valid:
                    rejected.append({'run_id':row['run_id'],'reason':'INCOMPATIBLE_OR_INSUFFICIENT_EVIDENCE'})
                    continue
                for oid in evidence['obligation_ids']:
                    if oid in required and oid not in covered:
                        if model_obligation_fingerprint(old_ir,oid)==required[oid]:
                            covered[oid] = row['run_id']
            except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
                rejected.append({'run_id':row['run_id'],'reason':'EVIDENCE_INTEGRITY_OR_FORMAT_ERROR'})
        missing = sorted(set(required)-set(covered))
        result = {'gate_id':_id('p2-gate'),'target':'model-incremental-prototype',
                  'policy_version':EVOLUTION_POLICY, 'spec_digest':digest(ir),
                  'decision':'Approved' if not missing else 'Blocked',
                  'required_obligations': sorted(required), 'covered_by_run':covered,
                  'missing_obligations':missing,'rejected':rejected,
                  'assurance':'Bounded' if not missing else 'None',
                  'scope_note':'Finite abstract-model evidence only, not C++ refinement or production release',
                  'created_at':_now()}
        # Persist a bounded, content-addressed decision for audit, never as a proof.
        result['decision_digest']=self.put(result)
        return result

    def record_impact(self, old_ir, new_ir):
        from .evolution import typed_graph, impact
        doc=impact(old_ir,new_ir)
        doc['old_graph_digest']=self.put(typed_graph(old_ir))
        doc['new_graph_digest']=self.put(typed_graph(new_ir))
        doc['impact_digest']=self.put(doc)
        return doc
