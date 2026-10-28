"""P2h end-to-end: genuine local C++ compilations and artifact-bound reuse."""
import json
from pathlib import Path
import shutil
import tempfile

import pytest
from axiom.cpp_project import load_project, run_project, project_gate
from axiom.lang import AxError
from axiom.store import Workspace

SRC = Path(__file__).resolve().parents[1]/'examples'/'cpp_project'

@pytest.fixture(scope='module')
def example():
    with tempfile.TemporaryDirectory(prefix='ax-p2h-suite-') as temp:
        p=Path(temp)/'project'
        shutil.copytree(SRC,p)
        ws=Workspace(Path(temp)/'evidence')
        mp=p/'project.json'
        original=(p/'format.cpp').read_text()
        first=run_project(ws,mp)
        yield p,ws,mp,original,first


def test_project_real_cpp_end_to_end(example):
    p,ws,mp,original,first=example
    assert first['report']['outcome']=='Tested'
    assert first['report']['executed_targets']==3
    assert first['report']['cache_hits']==0
    assert project_gate(ws,mp)['decision']=='Approved'
    assert project_gate(ws,mp)['release_authorized'] is False


def test_incremental_reuses_only_unchanged_targets(example):
    p,ws,mp,original,_=example
    unchanged=run_project(ws,mp)
    assert unchanged['report']['cache_hits']==2
    assert unchanged['report']['executed_targets']==1
    assert unchanged['report']['targets']['integration']['reused'] is False
    (p/'format.cpp').write_text(original+'\n// formatting implementation comment\n')
    assert project_gate(ws,mp)['decision']=='Blocked'
    updated=run_project(ws,mp)
    assert updated['report']['outcome']=='Tested'
    assert updated['report']['cache_hits']==1
    assert updated['report']['targets']['ledger']['reused'] is True
    assert updated['report']['targets']['format']['reused'] is False
    assert updated['report']['targets']['integration']['reused'] is False
    assert project_gate(ws,mp)['decision']=='Approved'


def test_real_defect_blocks_gate(example):
    p,ws,mp,original,_=example
    content=(p/'format.cpp').read_text()
    (p/'format.cpp').write_text(content.replace(' + ":" + ', ' + "-" + '))
    assert project_gate(ws,mp)['decision']=='Blocked'
    bad=run_project(ws,mp)
    assert bad['report']['outcome']=='Violated'
    assert bad['report']['targets']['ledger']['reused'] is True
    assert bad['report']['targets']['format']['outcome']=='Violated'
    assert bad['report']['targets']['integration']['outcome']=='Violated'
    assert project_gate(ws,mp)['decision']=='Blocked'
    (p/'format.cpp').write_text(original)
    assert project_gate(ws,mp)['decision']=='Approved'  # exact content restored


def test_untracked_sources_and_paths_fail_closed(example):
    p,ws,mp,original,_=example
    extra=p/'undeclared.cpp';extra.write_text('int hidden=0;')
    with pytest.raises(AxError,match='E_PROJECT_UNTRACKED'):load_project(mp)
    extra.unlink()
    obj=json.loads(mp.read_text())
    obj['tests'][0]['files'].append('../other.hpp')
    tmp=p/'project_bad.json';tmp.write_text(json.dumps(obj))
    with pytest.raises(AxError,match='E_PROJECT_TEST'):load_project(tmp)
    tmp.unlink()


def test_spec_version_change_invalidates_evidence(example):
    p,ws,mp,original,_=example
    spec=p/'ledger.ax'; old=spec.read_text()
    spec.write_text(old.replace('property Conservation', 'property ConservationRenamed'))
    assert project_gate(ws,mp)['decision']=='Blocked'
    spec.write_text(old)
    assert project_gate(ws,mp)['decision']=='Approved'
