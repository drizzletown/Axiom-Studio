"""Real HTTP integration tests for Axiom Studio and bundled engine."""
import hashlib
import json
import sys
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import unittest

STUDIO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STUDIO))
import server as app

class TestStudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv=app.create_server(0)
        cls.port=cls.srv.server_port
        cls.thread=threading.Thread(target=cls.srv.serve_forever,daemon=True)
        cls.thread.start()
        cls.token=cls.srv.studio.token
        cls.url=f'http://127.0.0.1:{cls.port}'
        cls.testfile=app.WORKSPACE/'studio_http_test.ax'
        cls.testfile.write_text((app.WORKSPACE/'two_account.ax').read_text(encoding='utf8'),encoding='utf8')
    @classmethod
    def tearDownClass(cls):
        cls.testfile.unlink(missing_ok=True)
        cls.srv.shutdown();cls.srv.server_close()

    def call(self,path,method='GET',data=None,token=True):
        headers={'X-Axiom-Token':self.token} if token else {}
        if data is not None:
            data=json.dumps(data).encode('utf-8');headers['Content-Type']='application/json'
        try:
            with urlopen(Request(self.url+path,data=data,method=method,headers=headers),timeout=18) as r:
                body=r.read();return r.status,json.loads(body) if r.headers.get('Content-Type','').startswith('application/json') else body
        except HTTPError as e:return e.code,json.loads(e.read())

    def job(self,action,path=None,**kwargs):
        code,initial=self.call('/api/run','POST',{'action':action,'path':path,**kwargs})
        self.assertEqual(code,202,initial)
        for _ in range(320):
            _,res=self.call('/api/job?id='+initial['job_id'])
            if res['status'] not in ('queued','running'):return res
            time.sleep(.12)
        self.fail('job timed out')

    def test_01_auth_token(self):
        code,res=self.call('/api/tree',token=False)
        self.assertEqual(code,403)
        code,res=self.call('/api/tree')
        self.assertEqual(code,200);self.assertGreater(len(res['files']),30)
        code,res=self.call('/index.html',token=False)
        self.assertEqual(code,403)

    def test_02_file_security(self):
        for bad in ['../engine/src/axiom/cli.py','/etc/passwd','cpp/../../requirements.txt']:
            code,res=self.call('/api/file?path='+__import__('urllib.parse').parse.quote(bad))
            self.assertEqual(code,400,res)
        status,doc=self.call('/api/file?path=studio_http_test.ax')
        self.assertEqual(status,200)
        self.assertIn('TwoAccount',doc['content'])
        code,res=self.call('/api/save','POST',{'path':'studio_http_test.ax','content':doc['content']+'\n','sha256':'not-the-hash'})
        self.assertEqual(code,409)
        code,res=self.call('/api/save','POST',{'path':'studio_http_test.ax','content':doc['content']+'\n','sha256':doc['sha256']})
        self.assertEqual(code,200);self.assertTrue(res['saved'])

    def test_03_file_creation(self):
        code,res=self.call('/api/create','POST',{'path':'studio_created.ax'})
        self.assertEqual(code,201,res)
        self.assertTrue((app.WORKSPACE/'studio_created.ax').is_file())
        code,res=self.call('/api/create','POST',{'path':'studio_created.ax'})
        self.assertEqual(code,400)
        code,res=self.call('/api/create','POST',{'path':'../created.ax'})
        self.assertEqual(code,400)
        (app.WORKSPACE/'studio_created.ax').unlink(missing_ok=True)

    def test_04_cli_model_workflow(self):
        for action in ['check','plan','verify','gate']:
            result=self.job(action,'two_account.ax')
            self.assertEqual(result['returncode'],0,(action,result['output'][-400:]))
            self.assertIsInstance(result['result'],dict)
        res=self.job('verify','broken_conservation.ax')
        self.assertEqual(res['returncode'],2)
        self.assertEqual(res['result']['verification']['outcome'],'Violated')
        self.assertIsNotNone(res['result']['verification']['counterexample'])

    def test_05_cpp_trust_and_gate(self):
        code,res=self.call('/api/run','POST',{'action':'cpp-project-verify','path':'cpp_project/project.json'})
        self.assertEqual(code,400);self.assertIn('确认',res['error'])
        code,res=self.call('/api/run','POST',{'action':'fake-shell','path':'two_account.ax'})
        self.assertEqual(code,400)
        r=self.job('cpp-project-verify','cpp_project/project.json',trusted=True)
        self.assertEqual(r['returncode'],0,r['output'][-900:])
        gate=self.job('cpp-project-gate','cpp_project/project.json')
        self.assertEqual(gate['returncode'],0,gate['output'][-900:])
        self.assertEqual(gate['result']['decision'],'Approved')

    def test_06_ai_handoff(self):
        code,res=self.call('/api/ai-task?path=two_account.ax')
        self.assertEqual(code,200,res)
        self.assertEqual(res['generator_connected'],False)
        self.assertEqual(res['obligations'],5)
        self.assertIn('TwoAccount',res['prompt'])
        self.assertIn('禁止：修改规格',res['prompt'])
        code,res=self.call('/api/ai-task?path=../engine/src/axiom/cli.py')
        self.assertEqual(code,400)

    def test_07_evidence_history(self):
        code,e=self.call('/api/evidence')
        self.assertEqual(code,200)
        self.assertGreater(len(e['runs']),0)
        code,h=self.call('/api/history')
        self.assertEqual(code,200)
        self.assertGreater(len(h['jobs']),0)
        code,status=self.call('/health',token=False)
        self.assertEqual(code,200);self.assertTrue(status['local_only'])

if __name__=='__main__':unittest.main(verbosity=2)
