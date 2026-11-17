import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
# SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = os.getenv(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1"
).split(",")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-a-secret")
# DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
# ALLOWED_HOSTS = ["*"]  # local development only

INSTALLED_APPS = [
    "django.contrib.humanize",
    "django.contrib.staticfiles",
    "store",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
STATIC_ROOT = BASE_DIR / "staticfiles"
ROOT_URLCONF = "chideman.urls"
WSGI_APPLICATION = "chideman.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "store.context.demo_customer",
    ]},
}]

DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "HOST": os.environ.get("DB_HOST", "localhost"),
    "PORT": os.environ.get("DB_PORT", "5432"),
    "NAME": os.environ.get("DB_NAME", "chideman"),
    "USER": os.environ.get("DB_USER", "chideman"),
    "PASSWORD": os.environ.get("DB_PASSWORD", "chideman"),
}}

# the AI service (agent container); the browser never talks to it directly
AGENT_URL = os.environ.get("AGENT_URL", "http://agent:8000")

# the demo persona lives in a signed cookie, so Django needs no tables of its own
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Detroit"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
