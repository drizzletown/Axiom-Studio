"""Axiom Studio 2.0.1 white UI / short help release checks.

These tests validate served assets and interface structure. They do not imply
native desktop user acceptance or executable C++ sandbox security.
"""
import sys
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

STUDIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDIO))
from server import create_server


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=set()
        self.details=[]
        self.styles=[]
    def handle_starttag(self, tag, attrs):
        data=dict(attrs)
        if 'id' in data:self.ids.add(data['id'])
        if tag=='details':self.details.append(data)
        if tag=='link' and data.get('rel')=='stylesheet':self.styles.append(data.get('href'))


class WhiteUIAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=create_server(0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.token=cls.server.studio.token
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, token=True):
        headers={'X-Axiom-Token':self.token} if token else {}
        try:
            with urlopen(Request(self.url+path,headers=headers),timeout=10) as res:
                return res.status,res.read().decode('utf8'),res.headers
        except HTTPError as ex:
            return ex.code,ex.read().decode('utf8'),ex.headers

    def test_01_stylesheet_served(self):
        status,css,headers=self.get('/light.css')
        self.assertEqual(status,200)
        self.assertIn('color-scheme:light',css)
        self.assertIn('background:#fff',css)
        self.assertIn('no-store',headers.get('Cache-Control',''))
        self.assertIn('text/css',headers.get('Content-Type',''))

    def test_02_help_and_uncluttered_home(self):
        status,html,_=self.get('/index.html')
        self.assertEqual(status,200)
        parser=Elements();parser.feed(html)
        for key in ('quickHelpOverlay','quickHelpClose','quickHelpStart','helpButton','journeyStartForm','productionTools','pilotHome'):
            self.assertIn(key,parser.ids)
        self.assertIn('/light.css',parser.styles)
        self.assertIn('<details class="production-tools"',html)
        self.assertIn('quick-help-overlay hidden',html)
        self.assertIn('1. 目标',html)
        self.assertIn('5. 交付',html)
        self.assertNotIn('STUDIO 1.8</span>',html)

    def test_03_private_html_remains_private(self):
        self.assertEqual(self.get('/index.html',False)[0],403)
        self.assertEqual(self.get('/api/tree',False)[0],403)

    def test_04_help_callbacks_and_short_guide(self):
        js=(STUDIO/'static/app.js').read_text(encoding='utf8')
        self.assertIn('q(\'#helpButton\').onclick=openQuickHelp',js)
        self.assertIn("q('#quickHelpStart').onclick=",js)
        self.assertIn('function closeQuickHelp()',js)
        guide=(STUDIO.parent/'docs/快速上手_2.0.1.md').read_text(encoding='utf8')
        self.assertLess(len(guide),600)
        self.assertIn('AI 候选需要人工审查',guide)

    def test_05_version(self):
        import json
        status,body,_=self.get('/api/meta')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['version'],'2.0.2')
        self.assertEqual((STUDIO.parent/'VERSION').read_text('utf8').strip(),'2.0.2')

if __name__=='__main__':unittest.main()
