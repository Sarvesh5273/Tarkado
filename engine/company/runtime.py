"""Private loopback development runtime; no automatic company network deployment."""

import os
import stat
from pathlib import Path


def private_directory(directory):
    directory = Path(directory).absolute()
    if directory.is_symlink():
        raise ValueError("Company state directory cannot be a symbolic link.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("Company state requires an owner-only directory; existing permissions are not changed.")
    return directory


def check_private_file(path):
    if path.is_symlink():
        raise ValueError("Company state files cannot be symbolic links.")
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Company state file must be a private regular file owned by this operator.")


def configure(directory, create=False, deployment=None):
    from django.conf import settings
    from django.core.management.utils import get_random_secret_key

    if settings.configured:
        raise ValueError("Company runtime is already configured; use a separate process for another installation.")
    directory = private_directory(directory)
    key_path = directory / ".secret-key"
    database = directory / "company.sqlite3"
    check_private_file(key_path)
    check_private_file(database)
    if create:
        if database.exists() or key_path.exists():
            raise ValueError("Bootstrap requires a new company store; existing state is never overwritten.")
        key = get_random_secret_key()
    elif not key_path.exists() and not database.exists():
        raise ValueError("Company installation is not initialized. Run 'company bootstrap' once with this --store path to enroll the first administrator. 'company upgrade' and 'company serve' require an existing installation.")
    elif not key_path.exists() or not database.exists():
        raise ValueError("Company store is incomplete: its database and matching secret-key file are both required. Do not bootstrap, reset, or replace existing files; inspect the store or restore a matching private backup.")
    else:
        with os.fdopen(os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as stream:
            key = stream.read()
    if len(key) != 50:
        raise ValueError("Company secret-key file is invalid; do not reset it to bypass corrupt state.")
    secure = {}
    if deployment is not None:
        from .deployment import validate_deployment
        deployment = validate_deployment({key: value for key, value in deployment.items() if key not in ("host", "origin")})
        secure = {"ALLOWED_HOSTS": [deployment["host"]], "CSRF_TRUSTED_ORIGINS": [deployment["origin"]],
                  "SESSION_COOKIE_SECURE": True, "CSRF_COOKIE_SECURE": True, "SECURE_SSL_REDIRECT": True,
                  "SECURE_HSTS_SECONDS": 31536000, "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
                  "SECURE_HSTS_PRELOAD": False, "TARKADO_PUBLIC_ORIGIN": deployment["origin"],
                  "TARKADO_SERVICE_MODE": "company_https_proxy"}
    options = dict(
        SECRET_KEY=key, DEBUG=False, ALLOWED_HOSTS=["localhost", "127.0.0.1", "[::1]"],
        ROOT_URLCONF="engine.company.urls", DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
                        "django_otp", "django_otp.plugins.otp_totp", "django_otp.plugins.otp_static", "engine.company"],
        MIDDLEWARE=["engine.company.middleware.DeploymentBoundaryMiddleware", "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
                    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
                    "django.contrib.auth.middleware.AuthenticationMiddleware", "django_otp.middleware.OTPMiddleware",
                    "engine.company.middleware.PrivateResponsesMiddleware"],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(database),
                               "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"}}},
        TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
                    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]}}],
        AUTH_PASSWORD_VALIDATORS=[
            {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
            {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 15}},
            {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
            {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
        ],
        USE_TZ=True, TIME_ZONE="UTC", LOGIN_URL="/login/", SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict", CSRF_COOKIE_HTTPONLY=True, CSRF_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_NAME="tarkado_sessionid", CSRF_COOKIE_NAME="tarkado_csrftoken",
        SESSION_EXPIRE_AT_BROWSER_CLOSE=True, SESSION_COOKIE_AGE=1800, X_FRAME_OPTIONS="DENY",
        OTP_TOTP_ISSUER="Tarkado", OTP_TOTP_SYNC=False, OTP_TOTP_THROTTLE_FACTOR=1,
        OTP_STATIC_THROTTLE_FACTOR=1, OTP_ADMIN_HIDE_SENSITIVE_DATA=True,
        DATA_UPLOAD_MAX_MEMORY_SIZE=131072, FILE_UPLOAD_MAX_MEMORY_SIZE=131072,
        TARKADO_COMPANY_DIRECTORY=str(directory),
        TARKADO_SERVICE_MODE="loopback_development",
        TARKADO_READINESS_VERIFIER=None,
        TARKADO_ADMISSION_VERIFIER=None,
        TARKADO_DELIVERY_VERIFIER=None,
        TARKADO_BILLING_VERIFIER=None,
    )
    options.update(secure)
    settings.configure(**options)
    import django
    django.setup()
    return directory


def initialize_store(directory):
    """Publish fresh private files only after enrollment inputs pass validation."""
    from django.conf import settings

    directory = Path(directory).absolute()
    if str(directory) != settings.TARKADO_COMPANY_DIRECTORY:
        raise ValueError("Cannot initialize a different company directory in this process.")
    key_path, database = directory / ".secret-key", directory / "company.sqlite3"
    if key_path.exists() or database.exists() or key_path.is_symlink() or database.is_symlink():
        raise ValueError("Existing company state is never overwritten or reset.")
    with os.fdopen(os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w") as stream:
        stream.write(settings.SECRET_KEY)
        stream.flush()
        os.fsync(stream.fileno())
    with os.fdopen(os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w"):
        pass
