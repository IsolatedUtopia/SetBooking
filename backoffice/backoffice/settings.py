"""Django 运营后台的设置。

三条关键约定：
1. 与 FastAPI 连接**同一个 MySQL 库** seat_booking；
2. 业务表的结构所有权归 FastAPI 侧的 Alembic，Django 不建表、不改表；
3. Django 自己要用的表（后台账号、权限、会话）由它自己的 migrate 创建，名字带前缀。
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dev-only-backoffice-secret-please-change"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "console",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backoffice.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backoffice.wsgi.application"
ASGI_APPLICATION = "backoffice.asgi.application"

# --- 数据库 -----------------------------------------------------------------
# 默认值只写了"非敏感"的部分；账号密码放在不提交的 local_settings.py 里。
DB_NAME = "seat_booking"
DB_USER = "seat"
DB_PASSWORD = ""
DB_HOST = "127.0.0.1"
DB_PORT = "3306"

try:  # 本机私有配置，已在 .gitignore 中忽略
    from .local_settings import *
except ModuleNotFoundError as exc:
    # 只有"这个模块本身不存在"才允许沉默；local_settings 内部导入失败要照常报错
    if exc.name != f"{__package__}.local_settings":
        raise

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": DB_NAME,
        "USER": DB_USER,
        "PASSWORD": DB_PASSWORD,
        "HOST": DB_HOST,
        "PORT": DB_PORT,
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
# 业务表统一存北京时间：连接层已 SET time_zone='+08:00'（见 app/db/session.py）。
# USE_TZ=False：Django 原样读、原样写、原样显示，不做 UTC 换算，
# 与 FastAPI 侧语义一致；运营在 Admin 里填 18:00 存的就是 18:00。
USE_TZ = False

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"