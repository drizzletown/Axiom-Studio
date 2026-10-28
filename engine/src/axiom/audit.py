"""Independent local-artifact consistency audit (NOT a trust anchor).

Verifies indices, checksummed objects, report/evidence cross-links, and stored
binary digests. A same-user adversary can still forge SQLite and all files;
only an external/isolated signer or verifier changes that trust model.
"""
from __future__ import annotations
from .lang import digest, validate
from .checker import obligations
from .store import toolchain_digest

AUDIT_VERSION='ax-local-evidence-audit/0.1'


def audit_workspace(workspace):
    findings=[]; examined={'model_runs':0,'cpp_runs':0,'product_runs':0,'content_objects':0}
    def err(table, row, code, detail=''):
        findings.append({'table':table,'record':str(row),'code':code,'detail':str(detail)[:160]})
    # Including orphaned objects catches content corruption outside currently indexed runs.
    for path in sorted(workspace.objects.iterdir()):
        if not path.is_file() or len(path.name)!=64:
            err('objects',path.name,'UNRECOGNIZED_ARTIFACT');continue
        examined['content_objects']+=1
        try:
            blob=path.read_bytes()
            if digest(blob)!='sha256:'+path.name:err('objects',path.name,'OBJECT_DIGEST_MISMATCH')
        except OSError as exc:err('objects',path.name,'OBJECT_READ_FAILED',exc)
    for row in workspace.runs():
        examined['model_runs']+=1;rid=row['run_id']
        try:
            ev=workspace.get(row['evidence_digest'])
            ir=workspace.get(ev['spec_digest'])
            validate(ir)
            witness=workspace.get(ev['witness_digest'])
            report=witness['report']
            if (ev['run_id']!=rid or row['spec_digest']!=ev['spec_digest'] or
                row['spec_digest']!=digest(ir) or witness['run_id']!=rid or
                witness['ir_digest']!=digest(ir)):
                err('runs',rid,'MODEL_LINK_MISMATCH')
            if not(row['outcome']==ev['outcome']==report['outcome']):
                err('runs',rid,'MODEL_OUTCOME_MISMATCH')
            ids={o['id'] for o in obligations(ir)}
            if set(ev['obligation_ids'])!=ids:err('runs',rid,'MODEL_OBLIGATION_MISMATCH')
            if report['outcome']=='Bounded':
                if report.get('scope',{}).get('finite_reachable_exhaustion') is not True:
                    err('runs',rid,'UNSUPPORTED_BOUNDED_ASSERTION')
                if set(report.get('verified_obligation_ids',[]))!=ids:
                    err('runs',rid,'MODEL_REPORT_COVERAGE_MISMATCH')
            if ev.get('tool_digest')!=toolchain_digest():
                # Audit warns about tool drift; drift is not by itself evidence tampering.
                err('runs',rid,'TOOL_VERSION_DRIFT')
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
            err('runs',rid,'MODEL_ARTIFACT_UNREADABLE',exc)
    for row in workspace.cpp_runs():
        examined['cpp_runs']+=1;rid=row['run_id']
        try:
            ev=workspace.get(row['evidence_digest'])
            report=workspace.get(ev['report_digest'])
            artifacts=ev['artifact_digests']
            if rid!=ev['run_id'] or not(
                row['spec_digest']==ev['spec_digest']==report['model_digest'] and
                row['source_digest']==ev['source_digest']==report['source_digest'] and
                row['binding_digest']==ev['binding_digest']==report['binding_digest'] and
                row['config_digest']==ev['config_digest']==report['config_digest']):
                err('cpp_runs',rid,'CPP_LINK_MISMATCH')
            if row['outcome']!=ev['outcome'] or ev['outcome']!=report['outcome']:
                err('cpp_runs',rid,'CPP_OUTCOME_MISMATCH')
            for field,target in [('source','source_digest'),('binding','binding_digest'),
                                 ('context','config_digest'),('harness','harness_digest')]:
                if artifacts[field]!=report[target]:err('cpp_runs',rid,'CPP_ARTIFACT_LINK_MISMATCH',field)
            for mode,h in ev.get('binary_digests',{}).items():
                if artifacts[mode]!=h or report['variants'][mode]['binary_digest']!=h:
                    err('cpp_runs',rid,'CPP_BINARY_LINK_MISMATCH',mode)
            for h in artifacts.values():
                obj=workspace.object_path(h)
                if digest(obj.read_bytes())!=h:err('cpp_runs',rid,'CPP_OBJECT_INTEGRITY_FAILED',h)
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
            err('cpp_runs',rid,'CPP_ARTIFACT_UNREADABLE',exc)
    # P2c independent synchronous-product evidence is separately indexed.
    # This checks recorded integrity, not whether two C++ binaries compose.
    with workspace._db() as db:
        product_table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_runs'").fetchone()
        prod_rows=list(db.execute('SELECT * FROM product_runs')) if product_table else []
    if prod_rows:
        from .product_store import product_tool_digest
        from .product import SCHEMA as PRODUCT_SCHEMA
        for row in prod_rows:
            examined['product_runs']+=1; rid=row['run_id']
            try:
                ev=workspace.get(row['evidence_digest'])
                report=workspace.get(ev['report_digest'])
                manifest=workspace.get(row['manifest_digest'])
                if (ev['schema']!='ax-product-evidence/0.1' or
                    manifest.get('schema')!=PRODUCT_SCHEMA or
                    ev['manifest_digest']!=row['manifest_digest'] or
                    ev['outcome']!=row['outcome'] or report['outcome']!=row['outcome']):
                    err('product_runs',rid,'PRODUCT_LINK_MISMATCH')
                if ev.get('tool_digest')!=product_tool_digest():
                    err('product_runs',rid,'PRODUCT_TOOL_DRIFT')
                if report['outcome']=='Bounded' and not (
                    report.get('scope',{}).get('finite_reachable_exhaustion') is True and
                    set(report.get('verified_properties',[]))=={x['name'] for x in manifest['properties']}):
                    err('product_runs',rid,'PRODUCT_BOUNDED_CLAIM_MISMATCH')
            except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                err('product_runs',rid,'PRODUCT_ARTIFACT_UNREADABLE',exc)
    # P2d mixed-interleaving evidence: local integrity only; signatures are separate.
    with workspace._db() as db:
        inter_table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='interleaving_runs'").fetchone()
        inter_rows=list(db.execute('SELECT * FROM interleaving_runs')) if inter_table else []
    if inter_rows:
        from .interleaving_store import interleaving_tool_digest
        from .interleaving import SCHEMA as INTER_SCHEMA
        examined['interleaving_runs']=0
        for row in inter_rows:
            examined['interleaving_runs']+=1;rid=row['run_id']
            try:
                ev=workspace.get(row['evidence_digest'])
                report=workspace.get(ev['report_digest'])
                manifest=workspace.get(row['manifest_digest'])
                if (ev['schema']!='ax-interleaving-evidence/0.1' or
                    manifest.get('schema')!=INTER_SCHEMA or
                    ev['manifest_digest']!=row['manifest_digest'] or
                    ev['outcome']!=row['outcome'] or report['outcome']!=row['outcome']):
                    err('interleaving_runs',rid,'INTER_LINK_MISMATCH')
                if ev.get('tool_digest')!=interleaving_tool_digest():
                    err('interleaving_runs',rid,'INTER_TOOL_DRIFT')
                if report['outcome']=='Bounded' and not (
                    report.get('scope',{}).get('finite_reachable_exhaustion') is True and
                    report.get('scope',{}).get('semantics')==INTER_SCHEMA and
                    set(report.get('verified_properties',[]))=={x['name'] for x in manifest['properties']}):
                    err('interleaving_runs',rid,'INTER_BOUNDED_CLAIM_MISMATCH')
            except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                err('interleaving_runs',rid,'INTER_ARTIFACT_UNREADABLE',exc)
    # P2e: local C++ finite-trace evidence is TEST EVIDENCE, not a proof of refinement.
    with workspace._db() as db:
        trace_table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cpp_trace_runs'").fetchone()
        trace_rows=list(db.execute('SELECT * FROM cpp_trace_runs')) if trace_table else []
    if trace_rows:
        from .trace_store import _tool_digest
        from .cpp_trace import TRACE_VERSION,CONTRACT_VERSION,HARNESS
        examined['cpp_trace_runs']=0
        for row in trace_rows:
            examined['cpp_trace_runs']+=1;rid=row['run_id']
            try:
                ev=workspace.get(row['evidence_digest'])
                report=workspace.get(ev['report_digest'])
                manifest=workspace.get(row['manifest_digest'])
                raw=workspace.object_path(row['source_digest']).read_bytes()
                if (ev['schema']!='ax-cpp-trace-evidence/0.1' or
                    ev['manifest_digest']!=row['manifest_digest'] or
                    ev['source_digest']!=row['source_digest'] or
                    ev['outcome']!=row['outcome'] or report['outcome']!=row['outcome'] or
                    report.get('schema')!=TRACE_VERSION or
                    report.get('manifest_digest')!=row['manifest_digest'] or
                    report.get('subject_digest')!=row['source_digest'] or
                    ev.get('abi')!=CONTRACT_VERSION or
                    ev.get('harness_digest')!=digest(HARNESS.encode()) or
                    digest(raw)!=row['source_digest']):
                    err('cpp_trace_runs',rid,'TRACE_LINK_MISMATCH')
                if ev.get('tool_digest')!=_tool_digest():
                    err('cpp_trace_runs',rid,'TRACE_TOOL_DRIFT')
                if report['outcome']=='Tested' and not (
                    ev.get('assurance')=='Tested' and
                    report['scope'].get('not_formal_refinement_proof') is True and
                    set(report['variants'])=={'normal','ubsan'} and
                    all(v.get('run_exit')==v.get('compile_exit')==0 and
                        v.get('compile_status')=='Finished' and v.get('run_status')=='Finished'
                        for v in report['variants'].values())):
                    err('cpp_trace_runs',rid,'TRACE_TEST_CLAIM_MISMATCH')
            except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                err('cpp_trace_runs',rid,'TRACE_ARTIFACT_UNREADABLE',exc)
    # P2f: native C++ thread histories are observed TEST evidence only.
    # This audit detects local inconsistencies, not forged self-consistent records.
    with workspace._db() as db:
        hist_table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cpp_history_runs'").fetchone()
        hist_rows=list(db.execute('SELECT * FROM cpp_history_runs')) if hist_table else []
    if hist_rows:
        from .history_store import history_tool_digest,EVIDENCE_VERSION,ABI_VERSION
        from .cpp_history import HISTORY_VERSION,HARNESS
        examined['cpp_history_runs']=0
        for row in hist_rows:
            examined['cpp_history_runs']+=1;rid=row['run_id']
            try:
                ev=workspace.get(row['evidence_digest'])
                report=workspace.get(ev['report_digest'])
                raw=workspace.object_path(row['source_digest']).read_bytes()
                if (ev['schema']!=EVIDENCE_VERSION or
                    ev['manifest_digest']!=row['manifest_digest'] or
                    ev['source_digest']!=row['source_digest'] or
                    ev['outcome']!=row['outcome'] or report['outcome']!=row['outcome'] or
                    report.get('schema')!=HISTORY_VERSION or
                    report.get('manifest_digest')!=row['manifest_digest'] or
                    report.get('subject_digest')!=row['source_digest'] or
                    ev.get('abi_version')!=ABI_VERSION or
                    ev.get('harness_digest')!=digest(HARNESS.encode()) or
                    digest(raw)!=row['source_digest']):
                    err('cpp_history_runs',rid,'HISTORY_LINK_MISMATCH')
                if ev.get('tool_digest')!=history_tool_digest():
                    err('cpp_history_runs',rid,'HISTORY_TOOL_DRIFT')
                if report['outcome']=='Tested' and not (
                    ev.get('assurance')=='Tested' and
                    report['scope'].get('not_exhaustive_native_schedules') is True and
                    report['scope'].get('not_formal_refinement_proof') is True and
                    report['scope'].get('not_production_release') is True and
                    set(report['variants'])=={'normal','ubsan'} and
                    all(v.get('run_exit')==v.get('compile_exit')==0 and
                        v.get('compile_status')=='Finished' and
                        v.get('run_status')=='Finished' and
                        v.get('checked_histories')==report['scope'].get('trials')
                        for v in report['variants'].values())):
                    err('cpp_history_runs',rid,'HISTORY_TEST_CLAIM_MISMATCH')
            except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                err('cpp_history_runs',rid,'HISTORY_ARTIFACT_UNREADABLE',exc)
    # P2g: source-bound seeded history/TSAN test evidence; replay audit is only local integrity.
    with workspace._db() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cpp_stress_runs'").fetchone()
        stress_rows=list(db.execute('SELECT * FROM cpp_stress_runs')) if exists else []
    if stress_rows:
        from .stress_store import tool_digest as stress_tool_digest, EVIDENCE as STRESS_EVIDENCE
        from .cpp_stress import SCHEMA as STRESS_SCHEMA,ABI as STRESS_ABI,STRESS_HARNESS
        examined['cpp_stress_runs']=0
        for row in stress_rows:
            examined['cpp_stress_runs']+=1;rid=row['run_id']
            try:
                ev=workspace.get(row['evidence_digest'])
                report=workspace.get(ev['report_digest'])
                source=workspace.object_path(row['source_digest']).read_bytes()
                scope=report['scope']
                if not(ev['schema']==STRESS_EVIDENCE and
                    report['schema']==STRESS_SCHEMA and
                    ev['manifest_digest']==row['manifest_digest']==report['manifest_digest'] and
                    ev['source_digest']==row['source_digest']==report['source_digest']==digest(source) and
                    ev['outcome']==row['outcome']==report['outcome'] and
                    ev['model_digests']==report['model_digests'] and
                    ev['abi']==STRESS_ABI and
                    ev['harness_digest']==report['harness_digest']==digest(STRESS_HARNESS.encode()) and
                    ev['scope']==scope):
                    err('cpp_stress_runs',rid,'STRESS_LINK_MISMATCH')
                if ev['tool_digest']!=stress_tool_digest():
                    err('cpp_stress_runs',rid,'STRESS_TOOL_DRIFT')
                if report['outcome']=='Tested' and not (
                    ev.get('assurance')=='Tested' and
                    scope.get('tsan_required') is True and scope.get('not_exhaustive') is True and
                    scope.get('not_formal_refinement_proof') is True and
                    scope.get('not_production_release') is True and
                    set(report['variants'])=={'normal','ubsan','tsan'} and
                    all(v.get('compile_exit')==v.get('run_exit')==0 and
                        v.get('compile_status')==v.get('run_status')=='Finished' and
                        v.get('checked_histories')==scope['trials']
                        for v in report['variants'].values())):
                    err('cpp_stress_runs',rid,'STRESS_TEST_CLAIM_MISMATCH')
            except (KeyError,ValueError,TypeError,OSError) as exc:
                err('cpp_stress_runs',rid,'STRESS_ARTIFACT_UNREADABLE',exc)
    # P0 index relationships are mutable; audit their references and displayed
    # decisions as consistency checks, never as cryptographic authorization.
    with workspace._db() as db:
        for row in db.execute('SELECT * FROM gates'):
            try:
                details=workspace.get(row['details_digest'])
                if (details['gate_id']!=row['gate_id'] or details['target']!=row['target'] or
                    details['spec_digest']!=row['spec_digest'] or details['policy_digest']!=row['policy_digest'] or
                    details['decision']!=row['decision'] or details['candidate_digest']!=row['candidate_digest']):
                    err('gates',row['gate_id'],'GATE_INDEX_MISMATCH')
            except (OSError,ValueError,KeyError,TypeError) as exc:
                err('gates',row['gate_id'],'GATE_ARTIFACT_UNREADABLE',exc)
        for row in db.execute('SELECT * FROM assessments'):
            try:
                origin=db.execute('SELECT * FROM runs WHERE run_id=?',(row['run_id'],)).fetchone()
                if origin is None:
                    err('assessments',row['assessment_id'],'ORPHANED_ASSESSMENT')
                    continue
                ev=workspace.get(origin['evidence_digest'])
                if row['freshness']=='Current':
                    if (row['target_spec_digest']!=ev['spec_digest'] or
                        ev['outcome']!='Bounded' or ev.get('tool_digest')!=toolchain_digest() or
                        ev['scope'].get('finite_reachable_exhaustion') is not True):
                        err('assessments',row['assessment_id'],'UNSUPPORTED_CURRENT_ASSERTION')
                elif row['freshness'] not in ('Stale','Revalidate'):
                    err('assessments',row['assessment_id'],'UNRECOGNIZED_ASSESSMENT')
            except (OSError,ValueError,KeyError,TypeError) as exc:
                err('assessments',row['assessment_id'],'ASSESSMENT_UNREADABLE',exc)
    return {'schema':AUDIT_VERSION,'status':'Consistent' if not findings else 'Findings',
            'findings':findings,'examined':examined,
            'trust_boundary':'Local integrity audit only. A writer with workspace access can forge '
                             'a self-consistent set of reports and digests.'}
