"""Axiom Studio 2.0: local release verification CLI. Never auto-approves native execution."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'studio'))
from server import Studio

def main():
    p=argparse.ArgumentParser(description='Axiom Studio 2.0 · 可信交付验证')
    sub=p.add_subparsers(dest='cmd',required=True)
    l=sub.add_parser('list');l.add_argument('--project')
    cr=sub.add_parser('plan');cr.add_argument('project_id');cr.add_argument('--graph');cr.add_argument('--previous')
    sh=sub.add_parser('show');sh.add_argument('id')
    run=sub.add_parser('verify');run.add_argument('id');run.add_argument('--trust-reviewed-native-code',action='store_true')
    ho=sub.add_parser('handoff');ho.add_argument('id');ho.add_argument('--output')
    args=p.parse_args();st=Studio();m=st.milestone20
    try:
        if args.cmd=='list':data=m.list(args.project)
        elif args.cmd=='plan':data=m.create(args.project_id,args.graph,args.previous)
        elif args.cmd=='show':data=m.get(args.id)
        elif args.cmd=='verify':
            data=m.start(args.id,args.trust_reviewed_native_code)
            while data['state']=='running':
                time.sleep(0.75);data=m.get(args.id)
        elif args.cmd=='handoff':
            data=m.handoff(args.id)
            if args.output:
                Path(args.output).write_text(json.dumps(data['report'],ensure_ascii=False,indent=2)+'\n','utf8')
                print('Written:',args.output)
        print(json.dumps(data,ensure_ascii=False,indent=2))
        if args.cmd=='verify' and data['state']!='passed':return 2
        return 0
    except Exception as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 1
    finally:
        st.executor.shutdown(wait=False,cancel_futures=True)
        m.pool.shutdown(wait=False,cancel_futures=True)

if __name__=='__main__':raise SystemExit(main())
