"""The Google sign-in box: the site seals the session to a one-time key of
the app, so the lovearound://signin link that carries it back is useless to
whoever else sees it (the process list, the browser's history, another app
that registered the scheme).

ECDH P-256 between our key and the page's (epk, the raw uncompressed point),
HKDF-SHA256 (no salt, info "lovearound signin v1") → AES-256-GCM key, the
state as associated data; box = 12-byte nonce + ciphertext + tag. Base64url
without padding. The page's half is in site/src/signin/index.html; the Mac
and Windows apps do the same.
"""
import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

INFO = b"lovearound signin v1"


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SignInKey:
    """One sign-in's key pair; the private half never leaves memory."""

    def __init__(self):
        self._private = ec.generate_private_key(ec.SECP256R1())

    @property
    def public(self):
        """For the page's key= parameter."""
        raw = self._private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return b64url(raw)

    def open(self, epk, box, state):
        """The session dict ({"uid", "email", "rt"}) from the link's epk and
        box; ValueError when it isn't ours or was tampered with."""
        try:
            theirs = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64url(epk))
            shared = self._private.exchange(ec.ECDH(), theirs)
            key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(shared)
            sealed = unb64url(box)
            plain = AESGCM(key).decrypt(sealed[:12], sealed[12:], state.encode())
            session = json.loads(plain)
        except Exception as error:  # bad base64, a point off the curve, a wrong tag, bad JSON
            raise ValueError("not our box") from error
        if not isinstance(session, dict):
            raise ValueError("not our box")
        return session


def seal(public, state, session):
    """The page's half, for tests: what site/src/signin/index.html does."""
    import os
    theirs = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64url(public))
    mine = ec.generate_private_key(ec.SECP256R1())
    shared = mine.exchange(ec.ECDH(), theirs)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(shared)
    nonce = os.urandom(12)
    sealed = AESGCM(key).encrypt(nonce, json.dumps(session).encode(), state.encode())
    epk = mine.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"epk": b64url(epk), "box": b64url(nonce + sealed)}
