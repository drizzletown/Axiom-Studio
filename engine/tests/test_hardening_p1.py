"""Execution-boundary regressions: risk acknowledgement and bounded process IO."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from axiom.cpp import _run_process, run_cpp
from axiom.cli import main
from axiom.lang import AxError, parse, validate

ROOT=Path(__file__).parents[1]


def test_cpp_cli_requires_trusted_input_acknowledgement(tmp_path,capsys):
    code=main(['--workspace',str(tmp_path), 'cpp-verify',str(ROOT/'examples/two_account.ax'),
               '--candidate',str(ROOT/'cpp/correct.cpp'), '--binding',str(ROOT/'cpp/binding.json')])
    assert code==5
    assert 'E_CPP_UNTRUSTED_EXECUTION' in capsys.readouterr().out


def test_reject_symlink_candidate(tmp_path):
    link=tmp_path/'sample.cpp';link.symlink_to(ROOT/'cpp/correct.cpp')
    ir=validate(parse((ROOT/'examples/two_account.ax').read_text()))
    with pytest.raises(AxError,match='E_CPP_SOURCE'):
        run_cpp(ir,link,ROOT/'cpp/binding.json')


def test_huge_stdout_capture_is_bounded(tmp_path):
    p=_run_process([sys.executable,'-c',"import sys; sys.stdout.write('x'*1200000)"] ,timeout_s=3,cwd=tmp_path)
    # RLIMIT_FSIZE should terminate the writer; returned capture is bounded.
    assert len(p['stdout']) <= 100000
    assert p['returncode'] != 0


def test_timeout_kills_process_group(tmp_path):
    p=_run_process([sys.executable,'-c','while True: pass'],timeout_s=0.3,cwd=tmp_path)
    assert p['timed_out'] or p['returncode'] != 0
    assert p['returncode'] is None or p['returncode'] != 0
