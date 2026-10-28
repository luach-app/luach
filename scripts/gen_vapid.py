"""Print a fresh VAPID key pair as env lines: python scripts/gen_vapid.py >> secrets.env"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    print(f"LUACH_VAPID_PUBLIC={b64(public)}")
    print(f"LUACH_VAPID_PRIVATE={b64(private)}")


if __name__ == "__main__":
    main()
