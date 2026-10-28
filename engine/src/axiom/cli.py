"""ax CLI for Axiom P0."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .lang import parse,validate,canonical_bytes,digest,AxError
from .checker import verify,obligations
from .store import Workspace

def emit(item):
    print(json.dumps(item,ensure_ascii=False,sort_keys=True,indent=2))

def load_spec(path):return validate(parse(Path(path).read_text(encoding='utf-8')))

def main(argv=None):
    parser=argparse.ArgumentParser(prog='ax',description='Axiom P0-P2h prototype CLI')
    parser.add_argument('--workspace',default='.axiom',help='local evidence workspace')
    subs=parser.add_subparsers(dest='command',required=True)
    check=subs.add_parser('check',help='parse, type-check and normalize a restricted .ax model')
    check.add_argument('spec');check.add_argument('--out',help='write Canonical IR JSON')
    plan=subs.add_parser('plan',help='derive model-level verification obligations')
    plan.add_argument('spec')
    ver=subs.add_parser('verify',help='finite-state model verification; store immutable evidence')
    ver.add_argument('spec');ver.add_argument('--max-states',type=int,default=50000)
    ver.add_argument('--max-transitions',type=int,default=250000)
    ver.add_argument('--timeout',type=float,default=30)
    gate=subs.add_parser('gate',help='evaluate model-only or cpp-target gate')
    gate.add_argument('spec');gate.add_argument('--target',choices=['model','cpp'],default='cpp')
    gate.add_argument('--candidate-digest')
    impact=subs.add_parser('impact',help='conservative assessment of earlier evidence')
    impact.add_argument('--from-spec',required=True);impact.add_argument('--to-spec',required=True)
    evo=subs.add_parser('evolve-impact',help='P2 typed semantic graph and conservative impact analysis')
    evo.add_argument('--from-spec',required=True);evo.add_argument('--to-spec',required=True)
    eg=subs.add_parser('evolve-gate',help='P2 model-only per-obligation compatible evidence gate')
    eg.add_argument('spec')
    co=subs.add_parser('compose-gate',help='P2b cross-model evidence dependency readiness (not integration proof)')
    co.add_argument('manifest')
    pv=subs.add_parser('product-verify',help='P2c exhaustive two-component atomic-synchronous abstract product')
    pv.add_argument('manifest');pv.add_argument('--max-states',type=int,default=10000)
    pv.add_argument('--max-transitions',type=int,default=100000)
    pv.add_argument('--timeout',type=float,default=20)
    pg=subs.add_parser('product-gate',help='P2c product evidence + fresh local model gates (not C++ approval)')
    pg.add_argument('manifest')
    iv=subs.add_parser('interleave-verify',help='P2d exhaustive mixed interleavings and rendezvous, abstract models only')
    iv.add_argument('manifest');iv.add_argument('--max-states',type=int,default=10000)
    iv.add_argument('--max-transitions',type=int,default=100000)
    iv.add_argument('--timeout',type=float,default=20)
    ig=subs.add_parser('interleave-gate',help='P2d mixed interleaving evidence + local model evidence')
    ig.add_argument('manifest')
    att=subs.add_parser('interleave-attest',help='offline Ed25519 signature after abstract gate + audit; trusted signer only')
    att.add_argument('manifest');att.add_argument('--private-key',required=True)
    att.add_argument('--signer',required=True);att.add_argument('--out',required=True)
    av=subs.add_parser('interleave-verify-attestation',help='independently verify pinned signer + fresh abstract gate')
    av.add_argument('manifest');av.add_argument('--public-key',required=True)
    av.add_argument('--signer',required=True);av.add_argument('--attestation',required=True)
    audit=subs.add_parser('audit',help='audit local stored evidence and content-addressed objects')
    ev=subs.add_parser('evidence',help='list immutable verification records')
    ev.add_argument('--spec')
    cpp=subs.add_parser('cpp-verify',help='compile and differentially test real C++ candidate (P1)')
    cpp.add_argument('spec');cpp.add_argument('--candidate',required=True);cpp.add_argument('--binding',required=True)
    cpp.add_argument('--trusted-local',action='store_true',help='explicitly accept risk of running trusted local C++ without OS sandbox')
    cpp.add_argument('--compiler',default='g++');cpp.add_argument('--optimization',choices=['0','1','2'],default='1')
    cg=subs.add_parser('cpp-gate',help='check actual recorded model AND matching candidate evidence')
    cg.add_argument('spec');cg.add_argument('--candidate',required=True);cg.add_argument('--binding',required=True)
    cg.add_argument('--compiler',default='g++');cg.add_argument('--optimization',choices=['0','1','2'],default='1')
    tprobe=subs.add_parser('sandbox-probe',help='experimental Linux namespace isolation availability')
    tv=subs.add_parser('cpp-trace-verify',help='P2e deterministic C++ multi-step trace differential checks inside Linux namespaces')
    tv.add_argument('manifest');tv.add_argument('--candidate',required=True)
    tv.add_argument('--depth',type=int,choices=[1,2,3,4,5],default=4)
    tg=subs.add_parser('cpp-trace-gate',help='P2e C++ finite-trace evidence + fresh abstract interleaving gate')
    tg.add_argument('manifest');tg.add_argument('--candidate',required=True)
    tg.add_argument('--depth',type=int,choices=[1,2,3,4,5],default=4)
    hv=subs.add_parser('cpp-history-verify',help='P2f real C++ std::thread history tests against Axiom linearizability')
    hv.add_argument('manifest');hv.add_argument('--candidate',required=True)
    hv.add_argument('--repeats',type=int,default=8)
    hg=subs.add_parser('cpp-history-gate',help='P2f source-bound native-thread observed-history test gate')
    hg.add_argument('manifest');hg.add_argument('--candidate',required=True)
    hg.add_argument('--repeats',type=int,default=8)
    sv=subs.add_parser('cpp-stress-verify',help='P2g native seeded scheduling + mandatory ThreadSanitizer')
    sv.add_argument('manifest');sv.add_argument('--candidate',required=True)
    sv.add_argument('--repeats',type=int,default=1)
    sv.add_argument('--seed',type=int,default=104729)
    sv.add_argument('--seed-count',type=int,default=2)
    ph=subs.add_parser('cpp-project-verify',help='P2h trusted local multi-file C++ integration and incremental regression tests')
    ph.add_argument('manifest');ph.add_argument('--full',action='store_true',help='do not reuse eligible target evidence')
    pgh=subs.add_parser('cpp-project-gate',help='P2h source/toolchain/spec-bound local test gate')
    pgh.add_argument('manifest')
    sg=subs.add_parser('cpp-stress-gate',help='P2g source-bound and seed-bound prototype quality gate')
    sg.add_argument('manifest');sg.add_argument('--candidate',required=True)
    sg.add_argument('--repeats',type=int,default=1)
    sg.add_argument('--seed',type=int,default=104729)
    sg.add_argument('--seed-count',type=int,default=2)
    args=parser.parse_args(argv)
    try:
        if args.command=='sandbox-probe':
            from .sandbox import available
            ok=available()
            emit({'available':ok,'kind':'experimental-user-mount-net-pid-chroot',
                  'production_untrusted_execution_safe':False})
            if not ok:return 3
        elif args.command=='cpp-project-verify':
            from .cpp_project import run_project
            result=run_project(Workspace(args.workspace),args.manifest,reuse=not args.full)
            emit(result)
            if result['report']['outcome']=='Violated':return 2
            if result['report']['outcome']=='Unknown':return 3
        elif args.command=='cpp-project-gate':
            from .cpp_project import project_gate
            result=project_gate(Workspace(args.workspace),args.manifest)
            emit(result)
            if result['decision']!='Approved':return 4
        elif args.command=='cpp-stress-verify':
            from .interleaving import load_interleaving
            from .stress_store import record_stress
            models,bound=load_interleaving(args.manifest)
            record=record_stress(Workspace(args.workspace),models,bound,args.candidate,
                repeats=args.repeats,seed=args.seed,seed_count=args.seed_count)
            emit({'record':{k:v for k,v in record.items() if k!='report'},'verification':record['report']})
            if record['outcome']=='Violated':return 2
            if record['outcome']=='Unknown':return 3
        elif args.command=='cpp-stress-gate':
            from .interleaving import load_interleaving
            from .stress_store import stress_gate
            models,bound=load_interleaving(args.manifest)
            report=stress_gate(Workspace(args.workspace),models,bound,args.candidate,
                repeats=args.repeats,seed=args.seed,seed_count=args.seed_count)
            emit(report)
            if report['decision']!='Approved':return 4
        elif args.command=='cpp-history-verify':
            from .interleaving import load_interleaving
            from .history_store import record_history
            models,bound=load_interleaving(args.manifest)
            record=record_history(Workspace(args.workspace),models,bound,args.candidate,repeats=args.repeats)
            emit({'record':{k:v for k,v in record.items() if k!='report'},'verification':record['report']})
            if record['outcome']=='Violated':return 2
            if record['outcome']=='Unknown':return 3
        elif args.command=='cpp-history-gate':
            from .interleaving import load_interleaving
            from .history_store import history_gate
            models,bound=load_interleaving(args.manifest)
            report=history_gate(Workspace(args.workspace),models,bound,args.candidate,repeats=args.repeats)
            emit(report)
            if report['decision']!='Approved':return 4
        elif args.command=='cpp-trace-verify':
            from .interleaving import load_interleaving
            from .trace_store import record_trace
            models,bound=load_interleaving(args.manifest)
            record=record_trace(Workspace(args.workspace),models,bound,args.candidate,depth=args.depth)
            emit({'record':{k:v for k,v in record.items() if k!='report'},'verification':record['report']})
            if record['outcome']=='Violated':return 2
            if record['outcome']=='Unknown':return 3
        elif args.command=='cpp-trace-gate':
            from .interleaving import load_interleaving
            from .trace_store import trace_gate
            models,bound=load_interleaving(args.manifest)
            report=trace_gate(Workspace(args.workspace),models,bound,args.candidate,depth=args.depth)
            emit(report)
            if report['decision']!='Approved':return 4
        elif args.command=='check':
            ir=load_spec(args.spec)
            if args.out:
                Path(args.out).parent.mkdir(parents=True,exist_ok=True)
                Path(args.out).write_bytes(canonical_bytes(ir)+b'\n')
            emit({"result":"OK","model":ir['model'],"ir_digest":digest(ir),
                  "schema_version":ir['schema_version'],"semantics_version":ir['semantics_version']})
        elif args.command=='plan':
            ir=load_spec(args.spec)
            emit({"spec_digest":digest(ir),"obligations":obligations(ir),
                  "notes":["model-level finite checking only; not proof of C++ implementation"]})
        elif args.command=='verify':
            ir=load_spec(args.spec)
            report=verify(ir,max_states=args.max_states,max_transitions=args.max_transitions,timeout_s=args.timeout)
            record=Workspace(args.workspace).record(ir,report)
            emit({"record":record,"verification":report})
            if report['outcome']=='Violated':return 2
            if report['outcome']=='Unknown':return 3
        elif args.command=='gate':
            ir=load_spec(args.spec)
            report=Workspace(args.workspace).gate(ir,args.target,args.candidate_digest)
            emit(report)
            if report['decision']!='Approved':return 4
        elif args.command=='impact':
            old=load_spec(args.from_spec);new=load_spec(args.to_spec)
            repo=Workspace(args.workspace)
            target=digest(new)
            assessments=[]
            for r in repo.runs():
                if r['spec_digest']==digest(old):assessments.append(repo.assess(r['run_id'],target))
            emit({"old_digest":digest(old),"new_digest":target,
                  "analysis":"exact semantic hashes only; changed IR conservatively invalidates all model evidence",
                  "assessments":assessments,
                  "revalidate":[x['run_id'] for x in assessments if x['freshness']!='Current']})
        elif args.command=='evolve-impact':
            old=load_spec(args.from_spec);new=load_spec(args.to_spec)
            emit(Workspace(args.workspace).record_impact(old,new))
        elif args.command=='evolve-gate':
            ir=load_spec(args.spec)
            result=Workspace(args.workspace).gate_model_evolved(ir)
            emit(result)
            if result['decision']!='Approved': return 4
        elif args.command=='cpp-verify':
            if not args.trusted_local:
                emit({'error':'E_CPP_UNTRUSTED_EXECUTION',
                      'detail':'P1/P2 has no secure compiler/runtime sandbox; use --trusted-local only for audited local examples'})
                return 5
            from .cpp import run_cpp
            ir=load_spec(args.spec)
            report,binaries=run_cpp(ir,args.candidate,args.binding,compiler=args.compiler,optimization=args.optimization)
            record=Workspace(args.workspace).record_cpp(ir,report,binaries)
            emit({'record':record,'verification':report})
            if report['outcome']=='Violated':return 2
            if report['outcome']=='Unknown':return 3
        elif args.command=='cpp-gate':
            ir=load_spec(args.spec)
            report=Workspace(args.workspace).gate_cpp(ir,args.candidate,args.binding,
                compiler=args.compiler,optimization=args.optimization)
            emit(report)
            if report['decision']!='Approved':return 4
        elif args.command=='product-verify':
            from .product import load_product,verify_product
            from .product_store import record_product
            models,bound=load_product(args.manifest)
            report=verify_product(models,bound,max_states=args.max_states,
                                  max_transitions=args.max_transitions,timeout_s=args.timeout)
            record=record_product(Workspace(args.workspace),models,bound,report)
            emit({'record':record,'verification':report})
            if report['outcome']=='Violated':return 2
            if report['outcome']=='Unknown':return 3
        elif args.command=='product-gate':
            from .product import load_product
            from .product_store import product_gate
            models,bound=load_product(args.manifest)
            report=product_gate(Workspace(args.workspace),models,bound)
            emit(report)
            if report['decision']!='Approved':return 4
        elif args.command=='interleave-verify':
            from .interleaving import load_interleaving,verify_interleaving
            from .interleaving_store import record_interleaving
            models,bound=load_interleaving(args.manifest)
            report=verify_interleaving(models,bound,max_states=args.max_states,
                                       max_transitions=args.max_transitions,timeout_s=args.timeout)
            record=record_interleaving(Workspace(args.workspace),models,bound,report)
            emit({'record':record,'verification':report})
            if report['outcome']=='Violated':return 2
            if report['outcome']=='Unknown':return 3
        elif args.command=='interleave-gate':
            from .interleaving import load_interleaving
            from .interleaving_store import interleaving_gate
            models,bound=load_interleaving(args.manifest)
            report=interleaving_gate(Workspace(args.workspace),models,bound)
            emit(report)
            if report['decision']!='Approved':return 4
        elif args.command=='interleave-attest':
            from .interleaving import load_interleaving
            from .attestation import sign_interleaving
            models,bound=load_interleaving(args.manifest)
            proof=sign_interleaving(Workspace(args.workspace),models,bound,args.private_key,args.signer)
            Path(args.out).write_bytes(canonical_bytes(proof)+b'\n')
            emit({'decision':'Signed','artifact':args.out,'subject':'finite-abstract-interleaving-only'})
        elif args.command=='interleave-verify-attestation':
            from .interleaving import load_interleaving
            from .attestation import verify_interleaving_attestation
            models,bound=load_interleaving(args.manifest)
            attestation=json.loads(Path(args.attestation).read_text(encoding='utf8'))
            report=verify_interleaving_attestation(Workspace(args.workspace),models,bound,attestation,
                                                   args.public_key,expected_signer=args.signer)
            emit(report)
            if report['decision']!='Approved':return 4
        elif args.command=='compose-gate':
            from .composition import assess_composition
            result=assess_composition(Workspace(args.workspace),args.manifest)
            emit(result)
            if result['decision']!='Ready':return 4
        elif args.command=='audit':
            from .audit import audit_workspace
            result=audit_workspace(Workspace(args.workspace))
            emit(result)
            if result['status']!='Consistent':return 4
        elif args.command=='evidence':
            repo=Workspace(args.workspace)
            rows=repo.runs()
            if args.spec:rows=[r for r in rows if r['spec_digest']==digest(load_spec(args.spec))]
            emit({"runs":rows})
        return 0
    except (AxError,ValueError,OSError,KeyError,TypeError) as ex:
        emit({"error":getattr(ex,'code','E_IO'),"detail":str(ex)})
        return 1

if __name__=='__main__':sys.exit(main())
