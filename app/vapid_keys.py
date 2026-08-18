from py_vapid import Vapid
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import os
import json
import base64

KEYS_FILE = os.path.join(os.path.dirname(__file__), 'instance', 'vapid_keys.json')


def get_vapid_keys():
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, 'r') as f:
            return json.load(f)

    vapid = Vapid()
    vapid.generate_keys()

    pub_key_raw = vapid.public_key.public_bytes(
        Encoding.X962,
        PublicFormat.UncompressedPoint
    )
    pub_key_b64 = base64.urlsafe_b64encode(pub_key_raw).rstrip(b'=').decode('utf-8')

    keys = {
        'private_key': vapid.private_pem().decode('utf-8'),
        'public_key': pub_key_b64,
    }

    os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
    with open(KEYS_FILE, 'w') as f:
        json.dump(keys, f)

    return keys


def get_public_key():
    keys = get_vapid_keys()
    return keys['public_key']


def get_private_key():
    keys = get_vapid_keys()
    return keys['private_key']


def get_private_key_der_b64():
    keys = get_vapid_keys()
    if 'private_key_der_b64' in keys:
        return keys['private_key_der_b64']

    from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PrivateFormat, NoEncryption
    import base64

    pem = keys['private_key']
    key = load_pem_private_key(pem.encode(), password=None)

    der = key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption()
    )

    der_b64 = base64.b64encode(der).decode()
    keys['private_key_der_b64'] = der_b64

    with open(KEYS_FILE, 'w') as f:
        import json
        json.dump(keys, f)

    return der_b64
