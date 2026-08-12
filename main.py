import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Flask, abort, flash, g, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from flask.sessions import SecureCookieSessionInterface


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.realpath(os.environ.get("FILE_SERVER_STATE_DIR", BASE_DIR))
if not os.path.isdir(STATE_DIR):
    raise RuntimeError(f"FILE_SERVER_STATE_DIR is not a directory: {STATE_DIR}")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
USERS_FILE = os.path.join(STATE_DIR, "users.json")
NAME_FILE = os.path.join(STATE_DIR, "name.json")
LOG_FILE = os.path.join(STATE_DIR, "log.txt")
DATA_LOCK = threading.RLock()


def make_private(path):
    """Best-effort owner-only permissions for files containing private data."""
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except (OSError, json.JSONDecodeError):
        return default


def save_json_private(path, value):
    """Atomically replace a JSON file and keep credentials/config owner-only."""
    directory = os.path.dirname(path)
    with DATA_LOCK:
        fd, temp_path = tempfile.mkstemp(prefix=".tmp-drive-", dir=directory, text=True)
        try:
            os.chmod(temp_path, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            make_private(path)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise


def load_config():
    value = load_json(CONFIG_FILE, {})
    return value if isinstance(value, dict) else {}


def get_secret_key():
    config = load_config()
    key = config.get("secret_key")
    if not isinstance(key, str) or len(key) < 32:
        key = secrets.token_hex(32)
        config["secret_key"] = key
        save_json_private(CONFIG_FILE, config)
    make_private(CONFIG_FILE)
    return key


def bounded_config_int(config, name, default, minimum, maximum):
    try:
        value = int(config.get(name, default))
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, value))


runtime_config = load_config()


class LocalProxyFix:
    """Trust forwarding headers only from a proxy running on this computer."""

    def __init__(self, application):
        self.application = application
        self.proxy_application = ProxyFix(
            application, x_for=1, x_proto=1, x_host=1, x_prefix=1
        )

    def __call__(self, environ, start_response):
        try:
            remote = ipaddress.ip_address(environ.get("REMOTE_ADDR", ""))
        except ValueError:
            remote = None
        application = self.proxy_application if remote and remote.is_loopback else self.application
        return application(environ, start_response)


class AdaptiveSecureCookieSessionInterface(SecureCookieSessionInterface):
    """Use Secure cookies through HTTPS tunnels while still supporting LAN HTTP."""

    def get_cookie_name(self, app):
        # Separate names prevent a browser from sending conflicting Secure and
        # non-Secure copies when the same server is used over LAN HTTP and a tunnel.
        return "drive_session_https" if request.is_secure else "drive_session_http"

    def get_cookie_secure(self, app):
        return request.is_secure

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or get_secret_key()
app.wsgi_app = LocalProxyFix(app.wsgi_app)
app.session_interface = AdaptiveSecureCookieSessionInterface()
app.config.update(
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    SESSION_REFRESH_EACH_REQUEST=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    MAX_CONTENT_LENGTH=bounded_config_int(
        runtime_config, "max_upload_bytes", 20 * 1024**3, 1024**2, 100 * 1024**3
    ),
)

limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")
csrf = CSRFProtect(app)

BOOT_TOKEN = secrets.token_hex(32)
MAX_FILES_PER_UPLOAD = 100
MAX_SEARCH_RESULTS = 250
MAX_SEARCH_ENTRIES = 50_000
MAX_EDIT_BYTES = 5 * 1024**2
MIN_FREE_DISK_BYTES = 256 * 1024**2
EXTENSION_RE = re.compile(r"^\.[A-Za-z0-9][A-Za-z0-9_-]{0,15}$")

ROLE_PERMISSIONS = {
    "owner": frozenset({"read", "upload", "create", "edit", "rename", "move", "convert", "delete"}),
    "editor": frozenset({"read", "upload", "create", "edit", "rename", "move", "convert"}),
    "viewer": frozenset({"read"}),
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".html", ".htm", ".css", ".json",
    ".xml", ".csv", ".sh", ".bash", ".zsh", ".fish", ".yaml", ".yml",
    ".ini", ".cfg", ".conf", ".config", ".log", ".env", ".toml", ".rs",
    ".go", ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".php",
    ".rb", ".swift", ".kt", ".kts", ".sql", ".r", ".tex", ".latex",
    ".svg", ".vue", ".jsx", ".tsx", ".scss", ".sass", ".less",
    ".dockerfile", ".makefile", ".mk", ".gradle", ".properties",
    ".gitignore", ".gitattributes", ".editorconfig", ".prettierrc",
    ".eslintrc", ".babelrc", ".npmrc", ".htaccess", ".nix", ".zig",
    ".lua", ".pl", ".pm", ".tcl", ".awk", ".sed", ".ps1", ".psm1",
    ".vb", ".vbs", ".bat", ".cmd", ".asm", ".s", ".dart", ".ex",
    ".exs", ".erl", ".hrl", ".clj", ".cljs", ".scala", ".groovy",
    ".tf", ".tfvars", ".hcl", ".proto", ".graphql", ".gql",
    ".patch", ".diff", ".rst", ".adoc", ".asciidoc",
}
INLINE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".avif"}
INLINE_VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogv", ".mov"}
INLINE_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a", ".opus"}


handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
make_private(LOG_FILE)
handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger = logging.getLogger("redstone")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(handler)


def clean_log_value(value):
    return str(value).replace("\r", "\\r").replace("\n", "\\n")[:1000]


def log(message):
    ip = clean_log_value(request.remote_addr or "unknown")
    username = clean_log_value(session.get("username", "anonymous"))
    logger.info("[%s] [%s] %s", ip, username, clean_log_value(message))


def load_app_name():
    value = load_json(NAME_FILE, {})
    if not isinstance(value, dict):
        return "Drive"
    name = value.get("name", "Drive")
    return name if isinstance(name, str) and name else "Drive"


def load_users():
    value = load_json(USERS_FILE, {})
    return value if isinstance(value, dict) else {}


def save_users(users):
    save_json_private(USERS_FILE, users)


def migrate_users_file():
    """Migrate legacy accounts to explicit roles without changing passwords."""
    users = load_users()
    if not users:
        return
    first_username = next(iter(users))
    changed = False
    for username, record in list(users.items()):
        if not isinstance(record, dict):
            users[username] = {}
            record = users[username]
            changed = True
        legacy_uuid = record.get("uuid")
        if isinstance(legacy_uuid, str) and legacy_uuid and not record.get("password"):
            record["password"] = legacy_uuid
            record.pop("uuid", None)
            changed = True
        old_role = record.get("role")
        if old_role == "admin":
            record["role"] = "owner"
            changed = True
        elif old_role == "user":
            record["role"] = "viewer"
            changed = True
        elif old_role not in ROLE_PERMISSIONS:
            record["role"] = "owner" if username == first_username else "viewer"
            changed = True
        if "storage_root" in record:
            record.pop("storage_root", None)
            changed = True
        if not record.get("credential_version"):
            record["credential_version"] = secrets.token_hex(16)
            changed = True
    if changed:
        save_users(users)
    else:
        make_private(USERS_FILE)


migrate_users_file()


def get_user(username):
    record = load_users().get(username)
    return record if isinstance(record, dict) else None


configured_root = runtime_config.get("root_dir")
ROOT_DIR = (
    os.path.realpath(os.path.expanduser(configured_root))
    if isinstance(configured_root, str) and configured_root
    else None
)


@app.before_request
def validate_session():
    g.csp_nonce = secrets.token_urlsafe(18)
    if request.endpoint in {"login", "static"}:
        return None
    if session.get("boot") != BOOT_TOKEN:
        session.clear()
        if request.endpoint != "logout":
            return redirect(url_for("login", next=request.path))
        return None
    username = session.get("username")
    user = get_user(username) if username else None
    if not user or session.get("credential_version") != user.get("credential_version"):
        session.clear()
        if request.endpoint != "logout":
            return redirect(url_for("login", next=request.path))
    return None


@app.after_request
def add_security_headers(response):
    nonce = getattr(g, "csp_nonce", "")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
        "img-src 'self' data: blob:; media-src 'self' blob:; "
        "frame-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'self'; form-action 'self'; connect-src 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if request.endpoint not in {"static"}:
        response.headers.setdefault("Cache-Control", "private, no-store")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.context_processor
def inject_globals():
    role = current_role() if session.get("username") else None
    return {
        "app_name": load_app_name(),
        "csp_nonce": getattr(g, "csp_nonce", ""),
        "account_role": role,
    }


def login_required(function):
    @wraps(function)
    def decorated(*args, **kwargs):
        username = session.get("username")
        if not username or not get_user(username):
            session.clear()
            return redirect(url_for("login", next=request.path))
        return function(*args, **kwargs)
    return decorated


def current_role():
    user = get_user(session.get("username"))
    return user.get("role", "viewer") if user else "viewer"


def has_permission(permission):
    return permission in ROLE_PERMISSIONS.get(current_role(), frozenset())


def permission_required(permission):
    def decorator(function):
        @wraps(function)
        @login_required
        def decorated(*args, **kwargs):
            if not has_permission(permission):
                abort(403, description="Your account does not have permission to do that.")
            return function(*args, **kwargs)
        return decorated
    return decorator


def global_root():
    if not ROOT_DIR or not os.path.isdir(ROOT_DIR):
        abort(503, description="Storage root is unavailable.")
    root = os.path.realpath(ROOT_DIR)
    project = os.path.realpath(BASE_DIR)
    if os.path.commonpath([root, project]) == root:
        abort(503, description="The storage root cannot contain the file-server application.")
    return root


def access_root():
    if not get_user(session.get("username")):
        abort(401)
    return global_root()


def normalized_parts(relative):
    if relative is None or relative == "":
        return []
    relative = str(relative).replace("\\", "/")
    if "\x00" in relative or relative.startswith("/"):
        abort(403)
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        log(f"BLOCKED unsafe path: {relative}")
        abort(403)
    return parts


def safe_path(relative=""):
    root = access_root()
    parts = normalized_parts(relative)
    candidate = os.path.abspath(os.path.join(root, *parts))
    if os.path.commonpath([root, candidate]) != root:
        log(f"BLOCKED path escape: {relative}")
        abort(403)

    current = root
    for part in parts:
        current = os.path.join(current, part)
        if os.path.lexists(current) and os.path.islink(current):
            log(f"BLOCKED symbolic link path: {relative}")
            abort(403)

    resolved = os.path.realpath(candidate)
    if os.path.commonpath([root, resolved]) != root:
        log(f"BLOCKED resolved path escape: {relative}")
        abort(403)
    return candidate


def require_non_root(path):
    if os.path.samefile(path, access_root()):
        abort(403, description="The storage root cannot be modified.")


def to_url_path(absolute_path):
    return Path(absolute_path).relative_to(access_root()).as_posix()


def parent_url_path(subpath):
    parts = normalized_parts(subpath)
    return "/".join(parts[:-1])


def get_file_category(ext):
    ext = ext.lower()
    if ext in INLINE_IMAGE_EXTENSIONS:
        return "image"
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".ogv", ".flv", ".wmv", ".m4v", ".3gp"}:
        return "video"
    if ext in {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a", ".wma", ".opus", ".aiff"}:
        return "audio"
    if ext == ".pdf":
        return "pdf"
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2", ".xz", ".zst"}:
        return "archive"
    return "file"


def safe_next_url(value):
    if not value or "\\" in value or any(ord(char) < 32 for char in value):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None
    return value


def login_rate_key():
    username = request.form.get("username", "").strip().casefold()[:100]
    return f"{get_remote_address()}:{username}"


@app.route("/login", methods=["GET", "POST"])
@csrf.exempt
@limiter.limit("5 per minute", key_func=login_rate_key)
def login():
    if session.get("boot") == BOOT_TOKEN and get_user(session.get("username")):
        return redirect(url_for("browse"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("uuid_pass", "").strip()
        user = get_user(username)
        stored_password = user.get("password", "") if user else ""
        valid = bool(user and isinstance(stored_password, str) and secrets.compare_digest(stored_password, password))
        if user and valid:
            session.clear()
            session.permanent = True
            session["username"] = username
            session["boot"] = BOOT_TOKEN
            session["credential_version"] = user.get("credential_version")
            log(f"LOGIN success user={username}")
            return redirect(safe_next_url(request.args.get("next", "")) or url_for("browse"))
        log(f"LOGIN failed user={username}")
        flash("Invalid username or password.")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    if session.get("username"):
        log("LOGOUT")
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return redirect(url_for("browse"))


def list_directories(root, limit=500):
    directories = []
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        dirnames[:] = [
            name for name in sorted(dirnames, key=str.casefold)
            if not os.path.islink(os.path.join(dirpath, name))
        ]
        for name in dirnames:
            full = os.path.join(dirpath, name)
            relative = Path(full).relative_to(root).as_posix()
            directories.append({
                "name": name,
                "path": relative,
                "depth": relative.count("/"),
            })
            if len(directories) >= limit:
                return directories
    return directories


@app.route("/browse", defaults={"subpath": ""}, strict_slashes=False)
@app.route("/browse/<path:subpath>", strict_slashes=False)
@login_required
def browse(subpath):
    absolute = safe_path(subpath)
    if not os.path.exists(absolute):
        abort(404)
    if not os.path.isdir(absolute):
        return redirect(url_for("view_file", subpath=subpath))
    log(f"BROWSE {subpath or '/'}")

    try:
        names = sorted(
            os.listdir(absolute),
            key=lambda name: (not os.path.isdir(os.path.join(absolute, name)), name.casefold()),
        )
    except PermissionError:
        flash("Permission denied reading this folder.")
        names = []

    entries = []
    for name in names:
        full = os.path.join(absolute, name)
        if os.path.islink(full):
            continue
        try:
            stat = os.stat(full)
        except OSError:
            continue
        ext = Path(name).suffix.lower()
        entries.append({
            "name": name,
            "is_dir": os.path.isdir(full),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "path": to_url_path(full),
            "ext": ext,
            "category": get_file_category(ext),
        })

    parts = normalized_parts(subpath)
    breadcrumbs = [{"name": part, "path": "/".join(parts[:index + 1])} for index, part in enumerate(parts)]
    return render_template(
        "browse.html",
        entries=entries,
        subpath=subpath,
        breadcrumbs=breadcrumbs,
        all_dirs=list_directories(access_root()) if has_permission("move") else [],
        username=session["username"],
        role=current_role(),
        can_edit=has_permission("edit"),
        can_upload=has_permission("upload"),
        can_delete=has_permission("delete"),
    )


@app.route("/download/<path:subpath>")
@login_required
def download_file(subpath):
    absolute = safe_path(subpath)
    if not os.path.isfile(absolute):
        abort(404)
    log(f"DOWNLOAD {subpath}")
    response = send_from_directory(
        os.path.dirname(absolute), os.path.basename(absolute), as_attachment=True, conditional=True
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/view/<path:subpath>")
@login_required
def view_file(subpath):
    absolute = safe_path(subpath)
    if not os.path.isfile(absolute):
        abort(404)
    log(f"VIEW {subpath}")
    ext = Path(absolute).suffix.lower()
    guessed_mime, _ = mimetypes.guess_type(absolute)
    inline = True
    if ext in TEXT_EXTENSIONS:
        mime = "text/plain; charset=utf-8"
    elif ext in INLINE_IMAGE_EXTENSIONS | INLINE_VIDEO_EXTENSIONS | INLINE_AUDIO_EXTENSIONS:
        mime = guessed_mime or "application/octet-stream"
    elif ext == ".pdf":
        mime = "application/pdf"
    else:
        mime = "application/octet-stream"
        inline = False
    response = send_from_directory(
        os.path.dirname(absolute),
        os.path.basename(absolute),
        mimetype=mime,
        as_attachment=not inline,
        conditional=True,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "sandbox; default-src 'none'; img-src 'self' data: blob:; "
        "media-src 'self' blob:; style-src 'unsafe-inline'; frame-ancestors 'self'"
    )
    return response


@app.route("/upload", defaults={"subpath": ""}, methods=["POST"], strict_slashes=False)
@app.route("/upload/<path:subpath>", methods=["POST"], strict_slashes=False)
@permission_required("upload")
def upload(subpath):
    absolute_dir = safe_path(subpath)
    if not os.path.isdir(absolute_dir):
        abort(404)
    files = request.files.getlist("files")
    if len(files) > MAX_FILES_PER_UPLOAD:
        flash(f"Too many files — maximum {MAX_FILES_PER_UPLOAD} per upload.")
        return redirect(url_for("browse", subpath=subpath))

    content_length = request.content_length or 0
    if shutil.disk_usage(absolute_dir).free < content_length + MIN_FREE_DISK_BYTES:
        flash("Upload rejected because the server is low on free disk space.")
        return redirect(url_for("browse", subpath=subpath))
    uploaded = 0
    skipped = 0
    for file_storage in files:
        if not file_storage.filename:
            continue
        filename = secure_filename(file_storage.filename)
        if not filename:
            skipped += 1
            continue
        destination = safe_path("/".join(filter(None, [subpath, filename])))
        try:
            with open(destination, "xb") as output:
                shutil.copyfileobj(file_storage.stream, output, length=1024 * 1024)
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
        except FileExistsError:
            skipped += 1
            continue
        except Exception:
            try:
                os.remove(destination)
            except OSError:
                pass
            raise
        log(f"UPLOAD {subpath}/{filename}")
        uploaded += 1
    if uploaded:
        flash(f"Uploaded {uploaded} file(s).")
    if skipped:
        flash(f"Skipped {skipped} invalid or already-existing file(s).")
    return redirect(url_for("browse", subpath=subpath))


@app.route("/mkdir", defaults={"subpath": ""}, methods=["POST"], strict_slashes=False)
@app.route("/mkdir/<path:subpath>", methods=["POST"], strict_slashes=False)
@permission_required("create")
def mkdir(subpath):
    name = secure_filename(request.form.get("name", "").strip())
    if name:
        destination = safe_path("/".join(filter(None, [subpath, name])))
        try:
            os.mkdir(destination, mode=0o700)
            log(f"MKDIR {subpath}/{name}")
            flash(f"Folder '{name}' created.")
        except FileExistsError:
            flash(f"'{name}' already exists.")
    return redirect(url_for("browse", subpath=subpath))


@app.route("/rename/<path:subpath>", methods=["POST"])
@permission_required("rename")
def rename(subpath):
    new_name = secure_filename(request.form.get("new_name", "").strip())
    parent = parent_url_path(subpath)
    if not new_name:
        flash("Invalid name.")
        return redirect(url_for("browse", subpath=parent))
    source = safe_path(subpath)
    if not os.path.exists(source):
        abort(404)
    require_non_root(source)
    destination = safe_path("/".join(filter(None, [parent, new_name])))
    if os.path.exists(destination):
        flash(f"'{new_name}' already exists.")
    else:
        os.rename(source, destination)
        log(f"RENAME {subpath} -> {parent}/{new_name}")
        flash(f"Renamed to '{new_name}'.")
    return redirect(url_for("browse", subpath=parent))


@app.route("/delete/<path:subpath>", methods=["POST"])
@permission_required("delete")
def delete(subpath):
    parent = parent_url_path(subpath)
    target = safe_path(subpath)
    if not os.path.exists(target):
        abort(404)
    require_non_root(target)
    name = os.path.basename(target)
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    log(f"DELETE {subpath}")
    flash(f"'{name}' deleted.")
    return redirect(url_for("browse", subpath=parent))


@app.route("/edit/<path:subpath>", methods=["GET", "POST"])
@permission_required("edit")
def edit_file(subpath):
    absolute = safe_path(subpath)
    parent = parent_url_path(subpath)
    if not os.path.isfile(absolute):
        abort(404)
    if os.path.getsize(absolute) > MAX_EDIT_BYTES:
        flash("This file is too large for the browser editor.")
        return redirect(url_for("browse", subpath=parent))
    ext = Path(absolute).suffix.lower()
    if ext not in TEXT_EXTENSIONS:
        flash("This file type cannot be edited.")
        return redirect(url_for("browse", subpath=parent))
    if request.method == "POST":
        content = request.form.get("content", "")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_EDIT_BYTES:
            abort(413)
        with open(absolute, "wb") as handle:
            handle.write(encoded)
        log(f"EDIT {subpath}")
        flash("File saved.")
        return redirect(url_for("browse", subpath=parent))
    try:
        with open(absolute, "r", encoding="utf-8") as handle:
            content = handle.read()
    except (UnicodeDecodeError, OSError):
        flash("Cannot edit this file because it is binary or unreadable.")
        return redirect(url_for("browse", subpath=parent))
    log(f"EDIT OPEN {subpath}")
    return render_template("edit.html", subpath=subpath, content=content, username=session["username"])


@app.route("/convert/<path:subpath>", methods=["POST"])
@permission_required("convert")
def convert_file(subpath):
    new_ext = request.form.get("new_ext", "").strip()
    parent = parent_url_path(subpath)
    if new_ext and not new_ext.startswith("."):
        new_ext = "." + new_ext
    if not EXTENSION_RE.fullmatch(new_ext):
        flash("Use an extension containing 1–16 letters, numbers, underscores, or dashes.")
        return redirect(url_for("browse", subpath=parent))
    source = safe_path(subpath)
    if not os.path.isfile(source):
        abort(404)
    new_name = Path(source).stem + new_ext.lower()
    destination = safe_path("/".join(filter(None, [parent, new_name])))
    if os.path.exists(destination):
        flash(f"'{new_name}' already exists.")
    else:
        shutil.copy2(source, destination)
        log(f"CONVERT {subpath} -> {parent}/{new_name}")
        flash(f"Copied as '{new_name}'.")
    return redirect(url_for("browse", subpath=parent))


@app.route("/move/<path:subpath>", methods=["POST"])
@permission_required("move")
def move_file(subpath):
    destination_relative = request.form.get("dest_dir", "").strip().replace("\\", "/")
    parent = parent_url_path(subpath)
    source = safe_path(subpath)
    if not os.path.exists(source):
        abort(404)
    require_non_root(source)
    destination_dir = safe_path(destination_relative)
    if not os.path.isdir(destination_dir):
        flash("The destination folder does not exist.")
        return redirect(url_for("browse", subpath=parent))
    if os.path.isdir(source) and os.path.commonpath([source, destination_dir]) == source:
        flash("A folder cannot be moved inside itself.")
        return redirect(url_for("browse", subpath=parent))
    destination = os.path.join(destination_dir, os.path.basename(source))
    if os.path.exists(destination):
        flash("A file with that name already exists in the destination.")
    else:
        shutil.move(source, destination)
        log(f"MOVE {subpath} -> {destination_relative or '/'}")
        flash(f"Moved to '{destination_relative or '/'}'.")
    return redirect(url_for("browse", subpath=parent))


@app.route("/search")
@login_required
@limiter.limit("20 per minute")
def search():
    query = request.args.get("q", "").strip()[:200]
    folded_query = query.casefold()
    results = []
    scanned = 0
    if folded_query:
        log(f"SEARCH length={len(query)}")
        root = access_root()
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if not os.path.islink(os.path.join(dirpath, name))]
            for name in dirnames + filenames:
                scanned += 1
                if scanned > MAX_SEARCH_ENTRIES:
                    break
                full = os.path.join(dirpath, name)
                if os.path.islink(full) or folded_query not in name.casefold():
                    continue
                ext = Path(name).suffix.lower()
                results.append({
                    "name": name,
                    "path": Path(full).relative_to(root).as_posix(),
                    "is_dir": os.path.isdir(full),
                    "category": get_file_category(ext),
                })
                if len(results) >= MAX_SEARCH_RESULTS:
                    break
            if scanned > MAX_SEARCH_ENTRIES or len(results) >= MAX_SEARCH_RESULTS:
                break
    return render_template("search.html", results=results, q=query, username=session["username"])


@app.errorhandler(413)
def request_too_large(_error):
    return render_template("error.html", code=413, message="That upload or edit is larger than this server allows."), 413


@app.errorhandler(CSRFError)
def csrf_error(_error):
    if request.endpoint == "login":
        next_url = safe_next_url(request.args.get("next", ""))
        session.clear()
        flash("The sign-in form was refreshed. Please submit it again.")
        return redirect(url_for("login", next=next_url) if next_url else url_for("login"))
    return render_template("error.html", code=400, message="This form expired. Refresh the page and try again."), 400


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message=error.description or "That action is not permitted."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="That file or page could not be found."), 404


@app.errorhandler(429)
def rate_limited(_error):
    return render_template("error.html", code=429, message="Too many requests. Wait a moment and try again."), 429


@app.errorhandler(503)
def unavailable(error):
    return render_template("error.html", code=503, message=error.description or "Storage is temporarily unavailable."), 503


if __name__ == "__main__":
    config = load_config()
    if len(sys.argv) >= 2:
        ROOT_DIR = os.path.realpath(os.path.expanduser(sys.argv[1]))
    elif config.get("root_dir"):
        ROOT_DIR = os.path.realpath(os.path.expanduser(config["root_dir"]))
    else:
        print("No root directory set.")
        print("Run: python set-default-dir.py")
        print("Or:  python main.py <directory> [port]")
        sys.exit(1)

    if not os.path.isdir(ROOT_DIR):
        print(f"'{ROOT_DIR}' is not a valid directory.")
        sys.exit(1)
    if os.path.commonpath([os.path.realpath(ROOT_DIR), os.path.realpath(BASE_DIR)]) == os.path.realpath(ROOT_DIR):
        print("The storage root cannot be the application directory or one of its parents.")
        print("Choose a dedicated data directory, such as this project's 'files' folder.")
        sys.exit(1)

    try:
        port = int(sys.argv[2]) if len(sys.argv) >= 3 else int(config.get("port", 5000))
    except (TypeError, ValueError):
        print("Port must be a number.")
        sys.exit(1)
    if not 1 <= port <= 65535:
        print("Port must be between 1 and 65535.")
        sys.exit(1)

    print(f"Root : {ROOT_DIR}")
    bind_host = str(config.get("bind_host", "0.0.0.0"))
    print(f"Local: http://127.0.0.1:{port}")
    print("LAN  : use this computer's LAN IP and the same port")
    print(f"Bind : {bind_host}:{port}")
    serve(app, host=bind_host, port=port, threads=8)
