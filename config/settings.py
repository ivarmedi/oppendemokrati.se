from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def _default_state_dir():
    if os.access(BASE_DIR, os.W_OK):
        return BASE_DIR
    return Path.cwd()


STATE_DIR = Path(os.environ.get("OD_STATE_DIR", _default_state_dir()))
DOWNLOAD_DIR = STATE_DIR / "data"


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_list(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _secret_key():
    path = os.environ.get("OD_SECRET_KEY_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get("OD_SECRET_KEY", "dev-only-change-me")


SECRET_KEY = _secret_key()
DEBUG = _env_flag("OD_DEBUG", default=True)
ALLOWED_HOSTS = _env_list("OD_ALLOWED_HOSTS", ["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = _env_list("OD_CSRF_TRUSTED_ORIGINS", [])

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "riksdag",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": STATE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 30},
    }
}

LANGUAGE_CODE = "sv-se"
TIME_ZONE = "Europe/Stockholm"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = STATE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PAGE_CACHE_SECONDS = 60 * 60 * 6 # 6 hours
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": STATE_DIR / "cache",
    }
}

if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
