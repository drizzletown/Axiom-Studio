"""2.0.2 single-flow UI acceptance: structure, asset serving, authority boundaries.

Browser visual smoke is separately exercised via an inline resource bridge in the
release environment and never represents native Windows UX testing.
"""
import json
import threading
from pathlib import Path
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server import create_server

class IDs(HTMLParser):
    def __init__(self):super().__init__();self.nodes={};self.refs=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.nodes[a['id']]=(tag,a)
        if tag in ('link','script'):self.refs.append(a.get('href') or a.get('src'))


def test_single_flow_five_phases_and_existing_controllers():
    html=(ROOT/'static/index.html').read_text(encoding='utf8')
    t=IDs();t.feed(html)
    for item in ('flowHome','flowSteps','flowProjectSelect','flowStartStage',
                 'flowRulesStage','flowBuildStage','flowVerifyStage','flowDeliveryStage',
                 'flowAdvanced','journeyStartForm','pilotHome','assemblyHome',
                 'milestone20Home','journeyReviewOverlay','quickHelpOverlay'):
        assert item in t.nodes, item
    assert t.nodes['flowAdvanced'][0]=='details'
    assert '/flow.css' in t.refs and '/flow.js' in t.refs
    assert '五步完成' in html and '5. 交付' in html
    assert t.nodes['flowVerifyStage'][1]['class'].endswith('hidden')
    assert t.nodes['flowDeliveryStage'][1]['class'].endswith('hidden')


def test_stage_adapter_does_not_mutate_protected_sources():
    src=(ROOT/'static/flow.js').read_text(encoding='utf8')
    assert "mount('journeyStartForm','flowStartFormMount')" in src
    assert "mount('pilotHome','flowPilotMount')" in src
    assert "mount('assemblyHome','flowAssemblyMount')" in src
    assert "mount('milestone20Home','flowVerifyMount')" in src
    assert '/api/journey' in src
    assert '/api/project/decide' not in src
    assert '/api/production/freeze' not in src
    assert '/api/milestone20/start' not in src
    assert 'AxiomFlowNewProject' in src
    css=(ROOT/'static/flow.css').read_text(encoding='utf8')
    assert '#projectDashboard > .journey{display:none' in css
    assert 'color:#fff' in css and 'background:#fff' in css


def test_served_resources_and_no_auth_bypass():
    srv=create_server(0)
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{srv.server_port}'
    try:
        for file,ctype in (('/flow.js','text/javascript'),('/flow.css','text/css')):
            with urlopen(base+file,timeout=10) as res:
                assert res.status==200 and ctype in res.headers.get('Content-Type','')
                assert 'no-store' in res.headers.get('Cache-Control','')
        try:urlopen(base+'/index.html',timeout=10);assert False,'private app opened without token'
        except HTTPError as e:assert e.code==403
        with urlopen(Request(base+'/api/meta',headers={'X-Axiom-Token':srv.studio.token}),timeout=10) as res:
            assert json.load(res)['version']=='2.0.2'
    finally:
        srv.shutdown();srv.server_close()
