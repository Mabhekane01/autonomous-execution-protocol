"""Signed envelopes (SPEC.md section 5): DSSE (the in-toto / Sigstore signing envelope) over ECDSA P-256 / SHA-256.

The signature covers DSSE's pre-authentication encoding, PAE(type, body) = "DSSEv1" SP LEN(type) SP type SP LEN(body)
SP body, so a signature over one payload type cannot be replayed as another. Signatures are 64 bytes, r || s, and
written in standard base64 as DSSE writes them; keys are base64url without padding: a private key is the 32-byte
scalar, a public key the 65-byte uncompressed point.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


class EnvelopeError(ValueError):
    """Refused: the reason in plain words."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64url(s: str) -> bytes:
    s = s.strip().rstrip("=")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except ValueError as e:
        raise EnvelopeError("not base64url") from e


def keypair() -> tuple[str, str]:
    """A new P-256 key pair: (private, public)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return _b64url(key.private_numbers().private_value.to_bytes(32, "big")), public_of_key(key)


def public_of_key(key: ec.EllipticCurvePrivateKey) -> str:
    return _b64url(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))


def _private(private: str) -> ec.EllipticCurvePrivateKey:
    raw = _unb64url(private)
    if len(raw) != 32:
        raise EnvelopeError("not a P-256 private key")
    try:
        return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
    except ValueError as e:
        raise EnvelopeError("not a P-256 private key") from e


def public_of(private: str) -> str:
    return public_of_key(_private(private))


def _public(public: str) -> ec.EllipticCurvePublicKey:
    raw = _unb64url(public)
    if len(raw) != 65 or raw[0] != 0x04:
        raise EnvelopeError("not an uncompressed P-256 public key")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as e:
        raise EnvelopeError("not a point on P-256") from e


def keyid(public: str) -> str:
    """The key's id in an envelope: the first 16 hex digits of SHA-256 of its base64url form."""
    return hashlib.sha256(public.encode()).hexdigest()[:16]


def pae(payload_type: str, payload: bytes) -> bytes:
    t = payload_type.encode()
    return b"DSSEv1 %d %s %d " % (len(t), t, len(payload)) + payload


def sign(private: str, payload_type: str, payload: bytes) -> dict:
    """A DSSE envelope with one signature."""
    if not payload_type:
        raise EnvelopeError("a payload type is required")
    der = _private(private).sign(pae(payload_type, payload), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return {"payloadType": payload_type, "payload": base64.b64encode(payload).decode(),
            "signatures": [{"keyid": keyid(public_of(private)), "sig": base64.b64encode(sig).decode()}]}  # fmt: skip


def verify(public: str, payload_type: str, envelope: dict) -> bytes:
    """The payload's bytes when a signature by `public` over this payload type verifies; refused otherwise."""
    if not isinstance(envelope, dict) or envelope.get("payloadType") != payload_type:
        raise EnvelopeError(f"not a {payload_type} envelope")
    sigs = [s for s in envelope.get("signatures") or [] if isinstance(s, dict) and s.get("keyid") == keyid(public)]
    if not sigs:
        raise EnvelopeError("not signed by this key")
    try:
        payload = base64.b64decode(str(envelope.get("payload", "")), validate=True)
        raw = base64.b64decode(str(sigs[0].get("sig", "")), validate=True)
    except ValueError as e:
        raise EnvelopeError("not base64") from e
    if len(raw) != 64:
        raise EnvelopeError("not a P-256 signature")
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    try:
        _public(public).verify(der, pae(payload_type, payload), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise EnvelopeError("the signature does not verify: refused") from e
    return payload
