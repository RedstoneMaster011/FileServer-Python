import os
import sys
import json
import shutil
import mimetypes
import secrets
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_from_directory, abort, flash
)
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from waitress import serve

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config["SESSION_PERMANENT"]          = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["MAX_CONTENT_LENGTH"]         = 20 * 1024 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"]    = True
app.config["SESSION_COOKIE_SAMESITE"]    = "Lax"
app.config["SESSION_COOKIE_SECURE"]      = True

limiter = Limiter(get_remote_address, app=app, default_limits=[])
csrf    = CSRFProtect(app)

BOOT_TOKEN           = secrets.token_hex(16)
MAX_FILES_PER_UPLOAD = 100
MAX_SEARCH_RESULTS   = 250

TEXT_EXTENSIONS = {
    '.txt', '.md', '.py', '.js', '.ts', '.html', '.htm', '.css', '.json',
    '.xml', '.csv', '.sh', '.bash', '.zsh', '.fish', '.yaml', '.yml',
    '.ini', '.cfg', '.conf', '.config', '.log', '.env', '.toml', '.rs',
    '.go', '.java', '.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.php',
    '.rb', '.swift', '.kt', '.kts', '.sql', '.r', '.tex', '.latex',
    '.svg', '.vue', '.jsx', '.tsx', '.scss', '.sass', '.less',
    '.dockerfile', '.makefile', '.mk', '.gradle', '.properties',
    '.gitignore', '.gitattributes', '.editorconfig', '.prettierrc',
    '.eslintrc', '.babelrc', '.npmrc', '.htaccess', '.nix', '.zig',
    '.lua', '.pl', '.pm', '.tcl', '.awk', '.sed', '.ps1', '.psm1',
    '.vb', '.vbs', '.bat', '.cmd', '.asm', '.s', '.dart', '.ex',
    '.exs', '.erl', '.hrl', '.clj', '.cljs', '.scala', '.groovy',
    '.tf', '.tfvars', '.hcl', '.proto', '.graphql', '.gql',
    '.patch', '.diff', '.rst', '.adoc', '.asciidoc',
}

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
USERS_FILE  = os.path.join(BASE_DIR, "users.json")
NAME_FILE   = os.path.join(BASE_DIR, "name.json")
LOG_FILE    = os.path.join(BASE_DIR, "log.txt")

@app.before_request
def validate_session():
    if request.endpoint in ("login", "static"):
        return
    if session.get("boot") != BOOT_TOKEN:
        session.clear()
        if request.endpoint != "logout":
            return redirect(url_for("login", next=request.path))

handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger = logging.getLogger("redstone")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

def log(msg):
    ip = request.remote_addr or "unknown"
    user = session.get("username", "anonymous")
    logger.info(f"[{ip}] [{user}] {msg}")

def load_app_name():
    if not os.path.exists(NAME_FILE):
        return "Drive"
    with open(NAME_FILE) as f:
        data = json.load(f)
    return data.get("name", "Drive")

@app.context_processor
def inject_app_name():
    return {"app_name": load_app_name()}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)

def get_secret_key():
    cfg = load_config()
    if "secret_key" not in cfg:
        cfg["secret_key"] = secrets.token_hex(32)
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    return cfg["secret_key"]

ROOT_DIR = None

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)

def get_user(username):
    return load_users().get(username)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

def safe_path(rel):
    rel    = rel.replace("\\", "/").lstrip("/")
    target = os.path.realpath(os.path.join(ROOT_DIR, rel))
    root   = os.path.realpath(ROOT_DIR)
    if target != root and not target.startswith(root + os.sep):
        log(f"BLOCKED path traversal attempt: {rel}")
        abort(403)
    return target

def to_url_path(abs_path):
    return Path(abs_path).relative_to(ROOT_DIR).as_posix()

def parent_url_path(subpath):
    p = str(Path(subpath.replace("\\", "/")).parent)
    return "" if p in (".", "") else p

def get_file_category(ext):
    ext = ext.lower()
    if ext in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico', '.avif', '.tiff', '.tif', '.heic', '.heif', '.raw'}:
        return 'image'
    if ext in {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.ogv', '.flv', '.wmv', '.m4v', '.3gp'}:
        return 'video'
    if ext in {'.mp3', '.wav', '.flac', '.ogg', '.aac', '.m4a', '.wma', '.opus', '.aiff'}:
        return 'audio'
    if ext == '.pdf':
        return 'pdf'
    if ext in TEXT_EXTENSIONS:
        return 'text'
    if ext in {'.zip', '.tar', '.gz', '.rar', '.7z', '.bz2', '.xz', '.zst'}:
        return 'archive'
    return 'file'

@app.route("/login", methods=["GET", "POST"])
@csrf.exempt
@limiter.limit("10 per minute")
def login():
    if session.get("boot") == BOOT_TOKEN and "username" in session:
        return redirect(url_for("browse"))
    if request.method == "POST":
        username  = request.form.get("username", "").strip()
        uuid_pass = request.form.get("uuid_pass", "").strip()
        user      = get_user(username)
        stored    = user["uuid"] if user else ""
        if user and secrets.compare_digest(uuid_pass, stored):
            session.clear()
            session["username"] = username
            session["boot"]     = BOOT_TOKEN
            log(f"LOGIN success user={username}")
            next_url = request.args.get("next", "")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("browse"))
        log(f"LOGIN failed user={username}")
        flash("Invalid username or UUID.")
    return render_template("login.html")

@app.route("/logout", methods=["GET", "POST"])
@csrf.exempt
def logout():
    log("LOGOUT")
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return redirect(url_for("browse"))

@app.route("/browse", defaults={"subpath": ""}, strict_slashes=False)
@app.route("/browse/<path:subpath>", strict_slashes=False)
@login_required
def browse(subpath):
    abs_path = safe_path(subpath)
    if not os.path.exists(abs_path):
        abort(404)
    if os.path.isfile(abs_path):
        return redirect(url_for("view_file", subpath=subpath))
    log(f"BROWSE {subpath or '/'}")

    try:
        names = sorted(
            os.listdir(abs_path),
            key=lambda n: (not os.path.isdir(os.path.join(abs_path, n)), n.lower())
        )
    except PermissionError:
        flash("Permission denied reading this folder.")
        names = []

    entries = []
    for name in names:
        full = os.path.join(abs_path, name)
        try:
            stat = os.stat(full)
        except OSError:
            continue
        ext = Path(name).suffix.lower()
        entries.append({
            "name":     name,
            "is_dir":   os.path.isdir(full),
            "size":     stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "path":     to_url_path(full),
            "ext":      ext,
            "category": get_file_category(ext),
        })

    parts = [p for p in subpath.replace("\\", "/").split("/") if p]
    breadcrumbs = [{"name": p, "path": "/".join(parts[:i+1])} for i, p in enumerate(parts)]

    return render_template(
        "browse.html",
        entries=entries,
        subpath=subpath,
        breadcrumbs=breadcrumbs,
        username=session["username"],
    )

@app.route("/download/<path:subpath>")
@login_required
def download_file(subpath):
    abs_path = safe_path(subpath)
    log(f"DOWNLOAD {subpath}")
    return send_from_directory(
        os.path.dirname(abs_path), os.path.basename(abs_path), as_attachment=True
    )

@app.route("/view/<path:subpath>")
@login_required
def view_file(subpath):
    abs_path = safe_path(subpath)
    log(f"VIEW {subpath}")
    mime, _  = mimetypes.guess_type(abs_path)
    return send_from_directory(
        os.path.dirname(abs_path), os.path.basename(abs_path),
        mimetype=mime or "application/octet-stream"
    )

@app.route("/upload", defaults={"subpath": ""}, methods=["POST"], strict_slashes=False)
@app.route("/upload/<path:subpath>", methods=["POST"], strict_slashes=False)
@login_required
def upload(subpath):
    abs_dir = safe_path(subpath)
    files   = request.files.getlist("files")
    if len(files) > MAX_FILES_PER_UPLOAD:
        flash(f"Too many files — max {MAX_FILES_PER_UPLOAD} per upload.")
        return redirect(url_for("browse", subpath=subpath))
    uploaded = 0
    for f in files:
        if f.filename:
            fname = secure_filename(f.filename)
            if fname:
                f.save(os.path.join(abs_dir, fname))
                log(f"UPLOAD {subpath}/{fname}")
                uploaded += 1
    if uploaded:
        flash(f"Uploaded {uploaded} file(s).")
    return redirect(url_for("browse", subpath=subpath))

@app.route("/mkdir", defaults={"subpath": ""}, methods=["POST"], strict_slashes=False)
@app.route("/mkdir/<path:subpath>", methods=["POST"], strict_slashes=False)
@login_required
def mkdir(subpath):
    name = secure_filename(request.form.get("name", "").strip())
    if name:
        os.makedirs(safe_path(os.path.join(subpath, name)), exist_ok=True)
        log(f"MKDIR {subpath}/{name}")
        flash(f"Folder '{name}' created.")
    return redirect(url_for("browse", subpath=subpath))

@app.route("/rename/<path:subpath>", methods=["POST"])
@login_required
def rename(subpath):
    new_name = request.form.get("new_name", "").strip()
    par      = parent_url_path(subpath)
    if new_name:
        new_safe = secure_filename(new_name)
        if not new_safe:
            flash("Invalid name.")
        else:
            src = safe_path(subpath)
            dst = safe_path(os.path.join(par, new_safe))
            if os.path.exists(dst):
                flash(f"'{new_safe}' already exists.")
            else:
                os.rename(src, dst)
                log(f"RENAME {subpath} -> {par}/{new_safe}")
                flash(f"Renamed to '{new_safe}'.")
    return redirect(url_for("browse", subpath=par))

@app.route("/delete/<path:subpath>", methods=["POST"])
@login_required
def delete(subpath):
    par    = parent_url_path(subpath)
    target = safe_path(subpath)
    name   = os.path.basename(target)
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    log(f"DELETE {subpath}")
    flash(f"'{name}' deleted.")
    return redirect(url_for("browse", subpath=par))

@app.route("/edit/<path:subpath>", methods=["GET", "POST"])
@login_required
def edit_file(subpath):
    abs_path = safe_path(subpath)
    par      = parent_url_path(subpath)
    ext      = Path(abs_path).suffix.lower()
    if ext not in TEXT_EXTENSIONS:
        flash("This file type cannot be edited.")
        return redirect(url_for("browse", subpath=par))
    if request.method == "POST":
        content = request.form.get("content", "")
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"EDIT {subpath}")
        flash("File saved.")
        return redirect(url_for("browse", subpath=par))
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, OSError):
        flash("Cannot edit this file (binary or unreadable).")
        return redirect(url_for("browse", subpath=par))
    log(f"EDIT OPEN {subpath}")
    return render_template("edit.html", subpath=subpath, content=content, username=session["username"])

@app.route("/convert/<path:subpath>", methods=["POST"])
@login_required
def convert_file(subpath):
    new_ext = request.form.get("new_ext", "").strip()
    par     = parent_url_path(subpath)
    if not new_ext:
        flash("No extension provided.")
        return redirect(url_for("browse", subpath=par))
    if not new_ext.startswith("."):
        new_ext = "." + new_ext
    src      = safe_path(subpath)
    new_name = Path(src).stem + new_ext
    dst      = safe_path(os.path.join(par, new_name))
    if os.path.exists(dst):
        flash(f"'{new_name}' already exists.")
    else:
        shutil.copy2(src, dst)
        log(f"CONVERT {subpath} -> {par}/{new_name}")
        flash(f"Copied as '{new_name}'.")
    return redirect(url_for("browse", subpath=par))

@app.route("/move/<path:subpath>", methods=["POST"])
@login_required
def move_file(subpath):
    dest_dir = request.form.get("dest_dir", "").strip().replace("\\", "/").lstrip("/")
    par      = parent_url_path(subpath)
    src      = safe_path(subpath)
    dst_dir  = safe_path(dest_dir)
    os.makedirs(dst_dir, exist_ok=True)
    dst_file = os.path.join(dst_dir, os.path.basename(src))
    if os.path.exists(dst_file):
        flash("A file with that name already exists in the destination.")
    else:
        shutil.move(src, dst_file)
        log(f"MOVE {subpath} -> {dest_dir or '/'}")
        flash(f"Moved to '{dest_dir or '/'}'.")
    return redirect(url_for("browse", subpath=par))

@app.route("/search")
@login_required
def search():
    q       = request.args.get("q", "").strip().lower()
    results = []
    if q:
        log(f"SEARCH {q!r}")
        for dirpath, dirnames, filenames in os.walk(ROOT_DIR):
            for name in dirnames + filenames:
                if q in name.lower():
                    full = os.path.join(dirpath, name)
                    ext  = Path(name).suffix.lower()
                    results.append({
                        "name":     name,
                        "path":     Path(full).relative_to(ROOT_DIR).as_posix(),
                        "is_dir":   os.path.isdir(full),
                        "category": get_file_category(ext),
                    })
                    if len(results) >= MAX_SEARCH_RESULTS:
                        break
            if len(results) >= MAX_SEARCH_RESULTS:
                break
    return render_template("search.html", results=results, q=q, username=session["username"])

if __name__ == "__main__":
    config = load_config()
    app.secret_key = os.environ.get("SECRET_KEY") or get_secret_key()

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

    port = int(sys.argv[2]) if len(sys.argv) >= 3 else config.get("port", 5000)

    print(f"Root : {ROOT_DIR}")
    print(f"URL  : http://127.0.0.1:{port} (Production)")
    serve(app, host='0.0.0.0', port=port, threads=8)