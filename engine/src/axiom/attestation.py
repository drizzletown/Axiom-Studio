"""P2d detached Ed25519 attestation for a *finite abstract interleaving gate*.

Signers must be a distinct trusted principal, with private key outside both
candidate and evidence workspace. Independent release systems must pin the
public key; an attacker controlling code/signing keys remains out of scope.
"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
from .lang import AxError,canonical_bytes,digest
from .interleaving import SCHEMA as INTER_SCHEMA
from .interleaving_store import interleaving_gate,interleaving_tool_digest
from .audit import audit_workspace

SCHEMA='ax-offline-abstract-attestation/0.1'


def _cryptography():
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key,load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        return load_pem_private_key,load_pem_public_key,Ed25519PrivateKey,Ed25519PublicKey,InvalidSignature
    except ImportError as exc:
        raise AxError('E_ATTEST_DEPENDENCY','install axiom-prototype[attest]') from exc


def _payload(ws,models,bound):
    gate=interleaving_gate(ws,models,bound)
    if gate['decision']!='Approved':
        raise AxError('E_ATTEST_GATE','abstract integration gate not approved')
    audit=audit_workspace(ws)
    if audit['status']!='Consistent':
        raise AxError('E_ATTEST_AUDIT','workspace integrity audit found discrepancies')
    selected=gate['selected_interleaving_evidence']
    ev=ws.get(selected['evidence_digest'])
    report=ws.get(ev['report_digest'])
    # Trust is derived from independent re-execution, not the mutable SQLite index.
    from .checker import verify
    from .interleaving import verify_interleaving
    for ir in models.values():
        local_report=verify(ir)
        if local_report.get('outcome')!='Bounded':
            raise AxError('E_ATTEST_LOCAL_REPLAY','model checker did not exhaust the local model')
    scoped=report['scope']
    replay=verify_interleaving(models,bound,max_states=scoped['max_states'],
                  max_transitions=scoped['max_transitions'],timeout_s=scoped['timeout_seconds'])
    if canonical_bytes(replay)!=canonical_bytes(report):
        raise AxError('E_ATTEST_REPLAY','current checker disagrees with stored result')
    return {'schema':'ax-offline-abstract-attestation-payload/0.1',
            'subject':'finite-two-component-mixed-interleaving-abstract-product',
            'manifest_digest':digest(bound),
            'evidence_digest':selected['evidence_digest'],
            'report_digest':ev['report_digest'],
            'model_digests':ev['model_digests'],
            'tool_digest':interleaving_tool_digest(),
            'report_outcome':report['outcome'],
            'assurance':'Bounded',
            'policy':'ax-interleaving-bounded-gate/0.1',
            'scope':'finite abstract interleavings only; no C++ refinement or production authorization'}


def sign_interleaving(ws,models,bound,private_key_path,signer_id):
    """Called by trusted OFFLINE signer; output is portable, detached JSON."""
    key_path=Path(private_key_path).resolve()
    if key_path.is_relative_to(ws.root.resolve()):
        raise AxError('E_ATTEST_KEY_LOCATION','private key must not be in evidence workspace')
    if not isinstance(signer_id,str) or not 1<=len(signer_id)<=80 or any(x in signer_id for x in '\n\r\x00'):
        raise AxError('E_ATTEST_SIGNER','invalid signer ID')
    load_priv,_,Priv,_,_=_cryptography()
    key=load_priv(key_path.read_bytes(),password=None)
    if not isinstance(key,Priv):raise AxError('E_ATTEST_KEY','key must be Ed25519')
    payload=_payload(ws,models,bound)
    signed={'schema':SCHEMA,'signer':signer_id,'payload':payload}
    signature=key.sign(canonical_bytes(signed))
    return {**signed,'signature':base64.b64encode(signature).decode('ascii')}


def verify_interleaving_attestation(ws,models,bound,attestation,public_key_path,*,expected_signer):
    """Return strict scoped acceptance; always recompute current independent gate.

    This function is NOT a general trusted execution attestation or a proof.
    """
    def block(code):
        return {'decision':'Blocked','reason':code,'target':'signed-finite-abstract-interleaving-gate'}
    if not isinstance(attestation,dict) or set(attestation)!={'schema','signer','payload','signature'} or attestation['schema']!=SCHEMA:
        return block('E_ATTEST_SCHEMA')
    if not isinstance(expected_signer,str) or not expected_signer or attestation['signer']!=expected_signer:
        return block('E_ATTEST_SIGNER')
    try:
        _,load_pub,_,Pub,InvalidSignature=_cryptography()
        pub=load_pub(Path(public_key_path).read_bytes())
        if not isinstance(pub,Pub):return block('E_ATTEST_KEY')
        signature=base64.b64decode(attestation['signature'],validate=True)
        signed={k:attestation[k] for k in ('schema','signer','payload')}
        pub.verify(signature,canonical_bytes(signed))
        current=_payload(ws,models,bound)
    except InvalidSignature:
        return block('E_ATTEST_BAD_SIGNATURE')
    except (AxError,OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
        return block(getattr(exc,'code','E_ATTEST_INVALID'))
    if attestation['payload']!=current:
        return block('E_ATTEST_STALE')
    return {'decision':'Approved','target':'signed-finite-abstract-interleaving-gate',
            'signer':expected_signer,'manifest_digest':current['manifest_digest'],
            'evidence_digest':current['evidence_digest'],
            'scope':current['scope']}
