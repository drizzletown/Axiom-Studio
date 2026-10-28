import copy
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from axiom.checker import verify
from axiom.store import Workspace
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving
from axiom.attestation import sign_interleaving,verify_interleaving_attestation
from axiom.lang import AxError

ROOT=Path(__file__).resolve().parents[1]/'examples'/'interleaving'

def setup(tmp_path):
    models,bound=load_interleaving(ROOT/'product_safe.json')
    ws=Workspace(tmp_path/'ws')
    for ir in models.values():ws.record(ir,verify(ir))
    record_interleaving(ws,models,bound,verify_interleaving(models,bound))
    private=Ed25519PrivateKey.generate()
    keypath=tmp_path/'signer.pem';pubpath=tmp_path/'trusted.pem'
    keypath.write_bytes(private.private_bytes(encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,encryption_algorithm=serialization.NoEncryption()))
    pubpath.write_bytes(private.public_key().public_bytes(encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    return models,bound,ws,keypath,pubpath


def test_valid_signature_and_signer(tmp_path):
    models,bound,ws,key,pub=setup(tmp_path)
    att=sign_interleaving(ws,models,bound,key,'qa-offline')
    assert verify_interleaving_attestation(ws,models,bound,att,pub,expected_signer='qa-offline')['decision']=='Approved'
    assert verify_interleaving_attestation(ws,models,bound,att,pub,expected_signer='other')['decision']=='Blocked'


def test_modified_payload_or_signature_rejected(tmp_path):
    models,bound,ws,key,pub=setup(tmp_path)
    att=sign_interleaving(ws,models,bound,key,'qa-offline')
    changed=copy.deepcopy(att);changed['payload']['report_outcome']='Proved'
    assert verify_interleaving_attestation(ws,models,bound,changed,pub,expected_signer='qa-offline')['reason']=='E_ATTEST_BAD_SIGNATURE'
    changed=copy.deepcopy(att);changed['signature']='!!!!'
    assert verify_interleaving_attestation(ws,models,bound,changed,pub,expected_signer='qa-offline')['decision']=='Blocked'


def test_wrong_public_key_rejected(tmp_path):
    models,bound,ws,key,pub=setup(tmp_path)
    att=sign_interleaving(ws,models,bound,key,'qa-offline')
    other=Ed25519PrivateKey.generate()
    pub.write_bytes(other.public_key().public_bytes(encoding=serialization.Encoding.PEM,format=serialization.PublicFormat.SubjectPublicKeyInfo))
    assert verify_interleaving_attestation(ws,models,bound,att,pub,expected_signer='qa-offline')['decision']=='Blocked'


def test_stale_model_or_manifest_rejected(tmp_path):
    models,bound,ws,key,pub=setup(tmp_path)
    att=sign_interleaving(ws,models,bound,key,'qa-offline')
    changed=copy.deepcopy(bound);changed['properties'][0]['name']='NewProperty'
    assert verify_interleaving_attestation(ws,models,changed,att,pub,expected_signer='qa-offline')['decision']=='Blocked'
    ws.object_path(att['payload']['report_digest']).write_bytes(b'{"hacked":true}')
    assert verify_interleaving_attestation(ws,models,bound,att,pub,expected_signer='qa-offline')['decision']=='Blocked'


def test_private_key_in_workspace_rejected(tmp_path):
    models,bound,ws,key,pub=setup(tmp_path)
    bad=ws.root/'key.pem';bad.write_bytes(key.read_bytes())
    with pytest.raises(AxError,match='E_ATTEST_KEY_LOCATION'):
        sign_interleaving(ws,models,bound,bad,'qa-offline')


def test_signing_blocked_without_verification(tmp_path):
    models,bound=load_interleaving(ROOT/'product_safe.json')
    ws=Workspace(tmp_path/'ws')
    private=Ed25519PrivateKey.generate();key=tmp_path/'key.pem'
    key.write_bytes(private.private_bytes(encoding=serialization.Encoding.PEM,format=serialization.PrivateFormat.PKCS8,
                                      encryption_algorithm=serialization.NoEncryption()))
    with pytest.raises(AxError,match='E_ATTEST_GATE'):
        sign_interleaving(ws,models,bound,key,'qa-offline')


def test_local_replay_prevents_synthesized_success_record(tmp_path):
    """A workspace writer cannot merely fabricate metadata and then get it signed."""
    models,bound,ws,key,pub=setup(tmp_path)
    from axiom.interleaving import verify_interleaving
    from axiom.interleaving_store import record_interleaving
    report=verify_interleaving(models,bound)
    report['statistics']['checked_transitions']+=1
    with pytest.raises(ValueError,match='FORGERY'):
        record_interleaving(ws,models,bound,report)


def test_signer_does_not_store_private_key_or_attestation_in_workspace(tmp_path):
    models,bound,ws,key,pub=setup(tmp_path)
    att=sign_interleaving(ws,models,bound,key,'external-qa')
    assert 'private_key' not in att
    assert all('PRIVATE KEY' not in p.read_text(errors='ignore') for p in ws.objects.iterdir())
