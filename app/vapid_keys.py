from py_vapid import Vapid
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import os
import json
import base64
import tempfile
import threading

from config import INSTANCE_DIR


_key_lock = threading.RLock()
KEYS_FILE = os.environ.get(
    "VAPID_KEYS_FILE",
    os.path.join(INSTANCE_DIR, "vapid_keys.json"),
)
_LEGACY_KEYS_FILE = os.path.join(os.path.dirname(__file__), "instance", "vapid_keys.json")


def _write_keys(keys):
    directory = os.path.dirname(KEYS_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".vapid-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(keys, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, KEYS_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _read_keys(path):
    with open(path, "r", encoding="utf-8") as file:
        keys = json.load(file)
    if not keys.get("private_key") or not keys.get("public_key"):
        raise ValueError("VAPID anahtar dosyası geçersiz")
    return keys


def _keys_from_env():
    """VAPID anahtarları ortam değişkenlerinden okunur.

    Render gibi geçici dosya sistemi olan platformlarda disk kalıcı değildir;
    her yeniden başlatmada yeni anahtar üretmek mevcut push aboneliklerini
    geçersiz kılar. Bu yüzden VAPID_PRIVATE_KEY ortam değişkeni önceliklidir.
    """
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if not private_key or not public_key:
        return None
    keys = {"private_key": private_key, "public_key": public_key}
    derived = os.environ.get("VAPID_PRIVATE_KEY_DER_B64", "").strip()
    if derived:
        keys["private_key_der_b64"] = derived
    return keys


def get_vapid_keys():
    env_keys = _keys_from_env()
    if env_keys is not None:
        return env_keys

    with _key_lock:
        current_path = os.path.abspath(KEYS_FILE)
        legacy_path = os.path.abspath(_LEGACY_KEYS_FILE)
        if os.path.exists(KEYS_FILE) and current_path != legacy_path:
            return _read_keys(KEYS_FILE)

        if os.path.exists(_LEGACY_KEYS_FILE):
            keys = _read_keys(_LEGACY_KEYS_FILE)
            if current_path != legacy_path:
                _write_keys(keys)
            return keys

        vapid = Vapid()
        vapid.generate_keys()
        public_key_raw = vapid.public_key.public_bytes(
            Encoding.X962,
            PublicFormat.UncompressedPoint,
        )
        public_key_b64 = base64.urlsafe_b64encode(
            public_key_raw,
        ).rstrip(b"=").decode("utf-8")
        keys = {
            "private_key": vapid.private_pem().decode("utf-8"),
            "public_key": public_key_b64,
        }
        _write_keys(keys)
        return keys


def get_public_key():
    keys = get_vapid_keys()
    return keys['public_key']


def get_private_key():
    return get_vapid_keys()['private_key']


def get_private_key_der_b64():
    keys = get_vapid_keys()
    if 'private_key_der_b64' in keys:
        return keys['private_key_der_b64']

    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        load_pem_private_key,
    )

    pem = keys['private_key']
    key = load_pem_private_key(pem.encode(), password=None)

    der = key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption()
    )

    der_b64 = base64.b64encode(der).decode()
    keys['private_key_der_b64'] = der_b64

    # Ortam anahtarı kullanılıyorsa diske yazılamaz; diske yazmadan döndür.
    if _keys_from_env() is not None:
        return der_b64

    with _key_lock:
        existing_keys = get_vapid_keys()
        if "private_key_der_b64" in existing_keys:
            return existing_keys["private_key_der_b64"]
        existing_keys["private_key_der_b64"] = der_b64
        _write_keys(existing_keys)

    return der_b64
