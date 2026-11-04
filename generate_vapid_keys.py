"""Generate the VAPID key pair web push needs (run once per environment).

Prints the two values to set on this service:
    VAPID_PUBLIC_KEY   handed to browsers when they subscribe (not secret)
    VAPID_PRIVATE_KEY  signs every push (secret: only in the environment)

Changing the pair later makes every existing subscription invalid; users
are subscribed again the next time they open Focusly.

Usage: python generate_vapid_keys.py
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64url(public_raw), b64url(private_raw)


if __name__ == "__main__":
    public, private = generate()
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
