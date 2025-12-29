from __future__ import annotations
import base64, os, json, hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

def run_hash(payload: dict) -> str:
    b = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(b).hexdigest()

def load_or_generate_keypair() -> tuple[bytes, bytes]:
    priv_pem = os.getenv("SIGNING_PRIVATE_KEY_PEM","").strip()
    pub_pem = os.getenv("SIGNING_PUBLIC_KEY_PEM","").strip()
    if priv_pem and pub_pem:
        return priv_pem.encode("utf-8"), pub_pem.encode("utf-8")

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_bytes, pub_bytes

def sign_hash(hash_hex: str, private_pem: bytes) -> str:
    priv = serialization.load_pem_private_key(private_pem, password=None)
    sig = priv.sign(bytes.fromhex(hash_hex))
    return base64.b64encode(sig).decode("utf-8")

def verify_hash(hash_hex: str, signature_b64: str, public_pem: bytes) -> bool:
    pub = serialization.load_pem_public_key(public_pem)
    try:
        pub.verify(base64.b64decode(signature_b64.encode("utf-8")), bytes.fromhex(hash_hex))
        return True
    except Exception:
        return False
