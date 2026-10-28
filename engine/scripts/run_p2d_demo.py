"""Deterministic P2d demo. Self-generated test key is EPHEMERAL, NOT a trust anchor."""
from __future__ import annotations
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from axiom.checker import verify
from axiom.store import Workspace
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving,interleaving_gate
from axiom.attestation import sign_interleaving,verify_interleaving_attestation
from axiom.audit import audit_workspace

ROOT=Path(__file__).resolve().parents[1]
with TemporaryDirectory(prefix='ax-p2d-') as tmp:
    ws=Workspace(Path(tmp)/'workspace')
    safe_model,safe_bound=load_interleaving(ROOT/'examples/interleaving/product_safe.json')
    broken_model,broken_bound=load_interleaving(ROOT/'examples/interleaving/product_broken.json')
    before=interleaving_gate(ws,safe_model,safe_bound)
    safe=verify_interleaving(safe_model,safe_bound)
    broken=verify_interleaving(broken_model,broken_bound)
    record_interleaving(ws,safe_model,safe_bound,safe)
    for ir in safe_model.values():ws.record(ir,verify(ir))
    after=interleaving_gate(ws,safe_model,safe_bound)
    key=Ed25519PrivateKey.generate()
    private=Path(tmp)/'offline-signer-private.pem'
    public=Path(tmp)/'offline-signer-public.pem'
    private.write_bytes(key.private_bytes(encoding=serialization.Encoding.PEM,
         format=serialization.PrivateFormat.PKCS8,encryption_algorithm=serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(encoding=serialization.Encoding.PEM,
         format=serialization.PublicFormat.SubjectPublicKeyInfo))
    proof=sign_interleaving(ws,safe_model,safe_bound,private,'test-only-offline')
    verified=verify_interleaving_attestation(ws,safe_model,safe_bound,proof,public,
                                             expected_signer='test-only-offline')
    output={
      'version':'0.6.0',
      'baseline':'Axiom 0.2 frozen; HLD V1.0 unchanged',
      'safe':{'outcome':safe['outcome'],'states':safe['statistics']['reachable_states'],
              'steps_checked':safe['statistics']['checked_transitions']},
      'broken':{'outcome':broken['outcome'],'reason':broken['reason'],
                'counterexample':broken['counterexample']},
      'gate_before_local_evidence':before['decision'],
      'gate_after_local_evidence':after['decision'],
      'attestation_with_ephemeral_test_key':verified['decision'],
      'workspace_integrity_audit':audit_workspace(ws)['status'],
      'scope':'finite abstract two-component atomic interleavings; NOT C++ refinement, secure execution, or production authorization'}
    assert safe['outcome']=='Bounded' and broken['outcome']=='Violated'
    assert before['decision']=='Blocked' and after['decision']==verified['decision']=='Approved'
    assert output['workspace_integrity_audit']=='Consistent'
    print(json.dumps(output,ensure_ascii=False,indent=2))
