import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "kredi-kart-takip-gizli-anahtar")

    _db_url = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(INSTANCE_DIR, 'app.db')}"
    )
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "true").lower() == "true"

    # Şifre sıfırlama e-postası. MAIL_SERVER tanımlı değilse sıfırlama
    # bağlantısı günlüğe yazılır ve e-posta gönderilmez.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER",
        "noreply@kredi-kart-takip.local",
    )
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT", "10"))

    # VAPID anahtarları diskte kalıcı değilse ortam değişkenlerinden okunur.
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
    VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
