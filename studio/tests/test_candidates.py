"""End-to-end HTTP tests, including actual compiler/test/gate for candidate workflow."""
import hashlib, json, os, shutil, sys, threading, time, unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

STUDIO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STUDIO))
import server as app

class TestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=app.create_server(0);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}';cls.token=cls.server.studio.token
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        self.root=app.WORKSPACE/('candidate_test_'+self._testMethodName)
        shutil.copytree(app.WORKSPACE/'cpp_project',self.root)
        self.manifest=f'{self.root.name}/project.json';self.target=f'{self.root.name}/ledger.cpp'
        self.good=(self.root/'ledger.cpp').read_text()
    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)
    def call(self,path,method='GET',data=None,auth=True):
        headers={'X-Axiom-Token':self.token} if auth else {}
        if data is not None:data=json.dumps(data).encode();headers['Content-Type']='application/json'
        try:
            with urlopen(Request(self.url+path,method=method,data=data,headers=headers),timeout=45) as r:return r.status,json.loads(r.read())
        except HTTPError as e:return e.code,json.loads(e.read())
    def create(self,code=None):
        status,p=self.call('/api/proposal/create','POST',{'manifest':self.manifest,'target':self.target,'code':code or self.good})
        self.assertEqual(status,201,p);return p
    def approve(self,p):
        return self.call('/api/proposal/review','POST',{'id':p['id'],'digest':p['code_sha256'],'approved':True})
    def apply(self,p):return self.call('/api/proposal/apply','POST',{'id':p['id']})
    def job(self,id,timeout=165):
        start=time.monotonic()
        while time.monotonic()-start<timeout:
            status,j=self.call('/api/job?id='+id);self.assertEqual(status,200)
            if j['status'] not in ('running','queued'):return j
            time.sleep(.3)
        self.fail('pipeline timeout')

    def test_security_and_manifest_scope(self):
        self.assertEqual(self.call('/api/proposals',auth=False)[0],403)
        for target in ('../engine/src/axiom/cli.py','cpp/correct.cpp','two_account.ax',self.root.name+'/test_ledger.cpp'):
            s,_=self.call('/api/proposal/create','POST',{'manifest':self.manifest,'target':target,'code':self.good})
            self.assertEqual(s,400,target)
        s,_=self.call('/api/proposal/create','POST',{'manifest':self.manifest,'target':self.target,'code':'a'*140000})
        self.assertEqual(s,400)
        s,_=self.call('/api/proposal/generate','POST',{'manifest':self.manifest,'target':self.target,'consent':False})
        self.assertEqual(s,400)

    def test_stage_review_apply_no_automatic_execution(self):
        p=self.create(self.good+'\n// generated proposal\n')
        self.assertEqual((self.root/'ledger.cpp').read_text(),self.good)
        self.assertEqual(self.call('/api/proposal/apply','POST',{'id':p['id']})[0],409)
        self.assertEqual(self.call('/api/proposal/review','POST',{'id':p['id'],'digest':'bad','approved':True})[0],409)
        self.assertEqual(self.call('/api/proposal/review','POST',{'id':p['id'],'digest':p['code_sha256'],'approved':False})[0],400)
        st,p1=self.approve(p);self.assertEqual(st,200,p1);self.assertEqual(p1['status'],'reviewed')
        st,p2=self.apply(p);self.assertEqual(st,200,p2);self.assertEqual(p2['status'],'applied')
        self.assertEqual((self.root/'ledger.cpp').read_text(),self.good+'\n// generated proposal\n')
        self.assertEqual(self.call('/api/proposal/validate','POST',{'id':p['id'],'trusted':False})[0],400)
        self.assertEqual(self.call('/api/proposal/apply','POST',{'id':p['id']})[0],409)
        self.assertEqual(self.call('/api/proposal?id='+p['id'])[1]['code'],self.good+'\n// generated proposal\n')
        self.assertTrue(p2['backup_sha256'])

    def test_source_or_spec_change_blocks_review(self):
        p=self.create()
        (self.root/'ledger.cpp').write_text(self.good+'\n// edit\n')
        self.assertEqual(self.approve(p)[0],409)
        (self.root/'ledger.cpp').write_text(self.good)
        p2=self.create()
        (self.root/'ledger.ax').write_text((self.root/'ledger.ax').read_text()+'\n// changed\n')
        self.assertEqual(self.approve(p2)[0],409)

    def test_manifest_change_or_late_edit_blocks(self):
        p=self.create(self.good+'\n// new\n')
        self.assertEqual(self.approve(p)[0],200)
        (self.root/'project.json').write_text((self.root/'project.json').read_text()+'\n')
        self.assertEqual(self.apply(p)[0],409)
        (self.root/'project.json').write_text((app.WORKSPACE/'cpp_project/project.json').read_text())
        p2=self.create(self.good+'\n// later\n')
        self.assertEqual(self.approve(p2)[0],200)
        self.assertEqual(self.apply(p2)[0],200)
        (self.root/'ledger.cpp').write_text(self.good+'\n// surprise\n')
        self.assertEqual(self.call('/api/proposal/validate','POST',{'id':p2['id'],'trusted':True})[0],409)
        p3=self.call('/api/proposal?id='+p2['id'])[1]
        self.assertFalse(p3['current'])

    def test_protected_test_files_invalidate_candidate(self):
        p=self.create(self.good+'\n// controlled candidate\n')
        self.assertEqual(self.approve(p)[0],200)
        (self.root/'test_ledger.cpp').write_text((self.root/'test_ledger.cpp').read_text()+'\n// changed test\n')
        self.assertEqual(self.apply(p)[0],409)

    def test_model_generator_local_stub_explicit_consent(self):
        good=self.good
        class Fake(BaseHTTPRequestHandler):
            captures=[]
            def log_message(self,*args):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers.get('Content-Length')));self.captures.append(json.loads(raw))
                result=json.dumps({'choices':[{'message':{'content':'```cpp\n'+good+'\n```'}}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
        server=ThreadingHTTPServer(('127.0.0.1',0),Fake);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        keys=['AXIOM_STUDIO_LLM_ENDPOINT','AXIOM_STUDIO_LLM_MODEL','AXIOM_STUDIO_LLM_API_KEY'];older={k:os.getenv(k) for k in keys}
        try:
            os.environ['AXIOM_STUDIO_LLM_ENDPOINT']=f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
            os.environ['AXIOM_STUDIO_LLM_MODEL']='stub-model';os.environ.pop('AXIOM_STUDIO_LLM_API_KEY',None)
            st,p=self.call('/api/proposal/generate','POST',{'manifest':self.manifest,'target':self.target,'consent':True})
            self.assertEqual(st,201,p);self.assertEqual(p['status'],'proposed');self.assertEqual(p['source'],'model')
            self.assertTrue(Fake.captures);self.assertIn('Axiom spec:',Fake.captures[0]['messages'][0]['content'])
            self.assertEqual((self.root/'ledger.cpp').read_text(),good)
        finally:
            server.shutdown();server.server_close()
            for k,v in older.items():
                if v is None:os.environ.pop(k,None)
                else:os.environ[k]=v

    def test_real_cpp_a_good_candidate_full_pipeline(self):
        p=self.create(self.good+'\n// reviewed AI candidate with same behavior\n')
        self.assertEqual(self.approve(p)[0],200);self.assertEqual(self.apply(p)[0],200)
        st,r=self.call('/api/proposal/validate','POST',{'id':p['id'],'trusted':True})
        self.assertEqual(st,202,r)
        j=self.job(r['job_id']);self.assertEqual(j['returncode'],0,j['output'][-2000:])
        self.assertEqual(j['result']['decision'],'Approved')
        self.assertEqual([c['step'] for c in j['result']['checks']],['spec-model','spec-gate','cpp-full','cpp-gate'])
        self.assertEqual(self.call('/api/proposal?id='+p['id'])[1]['status'],'verified')

    def test_real_cpp_b_bad_candidate_gate_blocked(self):
        bad=self.good.replace('from -= amount;','from += amount;')
        p=self.create(bad);self.assertEqual(self.approve(p)[0],200);self.assertEqual(self.apply(p)[0],200)
        st,r=self.call('/api/proposal/validate','POST',{'id':p['id'],'trusted':True});self.assertEqual(st,202,r)
        j=self.job(r['job_id']);self.assertEqual(j['result']['decision'],'Blocked',j['output'][-2200:])
        self.assertEqual(self.call('/api/proposal?id='+p['id'])[1]['status'],'blocked')

if __name__=='__main__':unittest.main()
