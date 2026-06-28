# -*- coding: utf-8 -*-
"""
𝑩𝑨𝑻𝑴𝑨𝑵 𝑫𝒆𝒗𓃠 - بانل استضافة كامل (نسخة مصححة ومطورة)
- تسجيل / دخول مع نظام موافقة الأدمن (pending/approved/rejected)
- إدارة سيرفرات (Python/Node.js) + مدير ملفات + كونسول
- خطط (plans) + API Keys + تكامل بوت تيليجرام
- كل الأسرار من Environment Variables
"""
import os
import re
import sys
import json
import time
import shutil
import signal
import socket
import secrets
import zipfile
import threading
import subprocess
from datetime import datetime, timedelta
from functools import wraps

import requests
from flask import (
    Flask, request, jsonify, session, redirect,
    send_from_directory, make_response,
)
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

# ----------------------------------------------------------------------
#  الإعدادات
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_DIR = os.path.join(DATA_DIR, "USERS")
DB_FILE = os.path.join(DATA_DIR, "db.json")
os.makedirs(USERS_DIR, exist_ok=True)

SECRET_KEY = os.environ.get("SECRET_KEY", "235f9f68fbfe16a1a9b0be6b6d27bb12694cab05cd850452ff49d281c40ead6a")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "16102010")

# بوت تيليجرام (اختياري) — توكن واحد موحّد من البيئة
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID", "")

# Groq AI (شات / طبيب أخطاء / مساعد كود) — المفتاح من البيئة
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = {"smart": "llama-3.3-70b-versatile", "fast": "llama-3.1-8b-instant"}
# معلومات الدفع (تظهر للمستخدم عند الترقية) — عدّلها من Environment Variables
PAY_VODAFONE = os.environ.get("PAY_VODAFONE", "01000000000")
PAY_INSTAPAY = os.environ.get("PAY_INSTAPAY", "batman@instapay")
PAY_NOTE = os.environ.get("PAY_NOTE", "بعد التحويل اضغط (أرسلت الدفع) وابعت صورة الإيصال للأدمن على تيليجرام لتفعيل الباقة فورًا.")

PORT_RANGE_START = 8100
PORT_RANGE_END = 9100

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

_lock = threading.Lock()

DEFAULT_PLANS = {
    "free": {"name": "\U0001f381 \u0645\u062c\u0627\u0646\u064a", "storage": 512, "ram": 256, "cpu": 0.5, "max_servers": 2, "price": 0},
    "4gb":  {"name": "\U0001f48e 4 \u062c\u064a\u062c\u0627", "storage": 4096, "ram": 1024, "cpu": 1, "max_servers": 5, "price": 5},
    "10gb": {"name": "\U0001f48e 10 \u062c\u064a\u062c\u0627", "storage": 10240, "ram": 2048, "cpu": 2, "max_servers": 10, "price": 10},
    "40gb": {"name": "\U0001f48e 40 \u062c\u064a\u062c\u0627", "storage": 40960, "ram": 4096, "cpu": 4, "max_servers": 20, "price": 25},
}


# ----------------------------------------------------------------------
#  قاعدة البيانات
# ----------------------------------------------------------------------
def _seed_db():
    db_data = {
        "users": {
            ADMIN_USER: {
                "password": generate_password_hash(ADMIN_PASS),
                "is_admin": True,
                "status": "approved",
                "created_at": _now(),
                "last_login": None,
                "plan": "admin",
                "max_servers": 999999,
                "storage_limit": 1024000,
                "api_key": None,
                "telegram_id": None,
            }
        },
        "servers": {},
        "plans": dict(DEFAULT_PLANS),
        "logs": [],
        "payments": [],
    }
    save_db(db_data)
    return db_data


def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("users", {})
            data.setdefault("servers", {})
            data.setdefault("plans", dict(DEFAULT_PLANS))
            data.setdefault("logs", [])
            data.setdefault("payments", [])
            # تأكد من وجود الأدمن
            if ADMIN_USER not in data["users"]:
                data["users"][ADMIN_USER] = {
                    "password": generate_password_hash(ADMIN_PASS),
                    "is_admin": True, "status": "approved", "created_at": _now(),
                    "last_login": None, "plan": "admin", "max_servers": 999999,
                    "storage_limit": 1024000, "api_key": None, "telegram_id": None,
                }
            return data
        except Exception:
            pass
    return _seed_db()


def save_db(db_data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_FILE)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


db = load_db()


# ----------------------------------------------------------------------
#  أدوات مساعدة
# ----------------------------------------------------------------------
def render_static(filename):
    return send_from_directory(TPL_DIR, filename)


def notify_admin(message):
    if not BOT_TOKEN or not ADMIN_TELEGRAM_ID:
        return
    try:
        requests.post(
            "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage",
            json={"chat_id": ADMIN_TELEGRAM_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def current_username():
    return session.get("username")


def is_admin(username):
    if not username:
        return False
    if username == ADMIN_USER:
        return True
    u = db["users"].get(username)
    return bool(u and u.get("is_admin"))


def generate_api_key():
    return secrets.token_urlsafe(32)


def get_user_by_api_key(api_key):
    if not api_key:
        return None, None
    for uname, udata in db["users"].items():
        if udata.get("api_key") == api_key:
            return uname, udata
    return None, None


def user_servers_dir(username):
    path = os.path.join(USERS_DIR, username, "SERVERS")
    os.makedirs(path, exist_ok=True)
    return path


def get_public_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=3).text
    except Exception:
        return "127.0.0.1"


def uptime_str(start_time):
    if not start_time:
        return "0 \u062b\u0627\u0646\u064a\u0629"
    diff = time.time() - start_time
    d = int(diff // 86400); h = int((diff % 86400) // 3600); m = int((diff % 3600) // 60)
    parts = []
    if d: parts.append(f"{d} \u064a\u0648\u0645")
    if h: parts.append(f"{h} \u0633\u0627\u0639\u0629")
    if m: parts.append(f"{m} \u062f\u0642\u064a\u0642\u0629")
    return " \u0648 ".join(parts) if parts else "\u0623\u0642\u0644 \u0645\u0646 \u062f\u0642\u064a\u0642\u0629"


def get_assigned_port():
    used = {s.get("port") for s in db["servers"].values() if s.get("port")}
    for port in range(PORT_RANGE_START, PORT_RANGE_END):
        if port not in used:
            return port
    return PORT_RANGE_START


def detect_main_file(srv_path, server_type):
    if server_type == "Node.js":
        pkg = os.path.join(srv_path, "package.json")
        if os.path.exists(pkg):
            try:
                with open(pkg, "r", encoding="utf-8") as f:
                    data = json.load(f)
                main = data.get("main", "")
                if main and os.path.exists(os.path.join(srv_path, main)):
                    return main
                m = re.search(r"node\s+(\S+\.js)", data.get("scripts", {}).get("start", ""))
                if m and os.path.exists(os.path.join(srv_path, m.group(1))):
                    return m.group(1)
            except Exception:
                pass
        for c in ["index.js", "bot.js", "app.js", "main.js", "server.js"]:
            if os.path.exists(os.path.join(srv_path, c)):
                return c
        js = [f for f in os.listdir(srv_path) if f.endswith(".js")]
        return js[0] if js else ""
    if server_type == "PHP":
        for c in ["index.php", "bot.php", "app.php", "main.php", "server.php"]:
            if os.path.exists(os.path.join(srv_path, c)):
                return c
        php = [f for f in os.listdir(srv_path) if f.endswith(".php")]
        return php[0] if php else "index.php"
    if server_type == "HTML":
        for c in ["index.html", "index.htm", "home.html"]:
            if os.path.exists(os.path.join(srv_path, c)):
                return c
        html = [f for f in os.listdir(srv_path) if f.endswith((".html", ".htm"))]
        return html[0] if html else "index.html"
    for c in ["main.py", "bot.py", "app.py", "index.py", "run.py", "start.py"]:
        if os.path.exists(os.path.join(srv_path, c)):
            return c
    py = [f for f in os.listdir(srv_path) if f.endswith(".py")]
    return py[0] if py else ""


def auto_install_deps(srv_path, server_type, log_path):
    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            if server_type == "Node.js":
                if os.path.exists(os.path.join(srv_path, "package.json")):
                    lf.write("\n\U0001f4e6 \u062a\u062b\u0628\u064a\u062a node_modules...\n"); lf.flush()
                    subprocess.run(["npm", "install"], cwd=srv_path, stdout=lf,
                                   stderr=subprocess.STDOUT, timeout=180)
                    lf.write("\u2705 \u062a\u0645 \u0627\u0644\u062a\u062b\u0628\u064a\u062a\n")
            else:
                if os.path.exists(os.path.join(srv_path, "requirements.txt")):
                    lf.write("\n\U0001f4e6 \u062a\u062b\u0628\u064a\u062a requirements.txt...\n"); lf.flush()
                    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                                   cwd=srv_path, stdout=lf, stderr=subprocess.STDOUT, timeout=300)
                    lf.write("\u2705 \u062a\u0645 \u0627\u0644\u062a\u062b\u0628\u064a\u062a\n")
    except Exception as e:
        try:
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n\u26a0\ufe0f \u062a\u062b\u0628\u064a\u062a: {e}\n")
        except Exception:
            pass


def start_server_process(folder):
    srv = db["servers"].get(folder)
    if not srv:
        return False, "\u0627\u0644\u0633\u064a\u0631\u0641\u0631 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f"
    server_type = srv.get("type", "Python")
    is_web = server_type == "HTML"
    main_file = srv.get("startup_file", "") or detect_main_file(srv["path"], server_type)
    if not main_file and not is_web:
        return False, "\u0644\u0627 \u064a\u0648\u062c\u062f \u0645\u0644\u0641 \u062a\u0634\u063a\u064a\u0644"
    if main_file:
        srv["startup_file"] = main_file
    if not is_web:
        fpath = os.path.join(srv["path"], main_file)
        if not os.path.exists(fpath):
            return False, f"\u0627\u0644\u0645\u0644\u0641 '{main_file}' \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f"
    port = srv.get("port") or get_assigned_port()
    srv["port"] = port
    log_path = os.path.join(srv["path"], "out.log")
    error_path = os.path.join(srv["path"], "errors.log")
    try:
        lf = open(log_path, "a", encoding="utf-8")
        lf.write(f"\n{'='*50}\n\U0001f680 \u0628\u062f\u0621 \u0627\u0644\u062a\u0634\u063a\u064a\u0644 - {datetime.now()}\n\U0001f4c1 {main_file}\n\U0001f50c {port}\n{'='*50}\n\n")
        lf.flush()
        env = os.environ.copy()
        env["PORT"] = str(port)
        if server_type == "Node.js":
            cmd = ["node", main_file]
        elif server_type == "PHP":
            cmd = ["php", main_file]
        elif server_type == "HTML":
            cmd = [sys.executable, "-u", "-m", "http.server", str(port), "--directory", srv["path"]]
        else:
            cmd = [sys.executable, "-u", main_file]
        proc = subprocess.Popen(
            cmd, cwd=srv["path"], stdout=lf,
            stderr=open(error_path, "a", encoding="utf-8"), env=env,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        srv["status"] = "Running"; srv["pid"] = proc.pid; srv["start_time"] = time.time()
        save_db(db)
        return True, "\u2705 \u062a\u0645 \u0627\u0644\u062a\u0634\u063a\u064a\u0644"
    except FileNotFoundError:
        return False, "\u274c \u0627\u0644\u0645\u0634\u063a\u0651\u0644 \u063a\u064a\u0631 \u0645\u062b\u0628\u0651\u062a (node/python/php)"
    except Exception as e:
        return False, str(e)


def stop_server_process(folder):
    srv = db["servers"].get(folder)
    if not srv:
        return
    pid = srv.get("pid")
    if pid:
        try:
            if hasattr(os, "killpg"):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except Exception:
                    pass
            if HAS_PSUTIL:
                try:
                    p = psutil.Process(pid)
                    for ch in p.children(recursive=True):
                        ch.kill()
                    p.kill()
                except Exception:
                    pass
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass
    srv["status"] = "Stopped"; srv["pid"] = None
    save_db(db)


def restart_server(folder):
    stop_server_process(folder)
    time.sleep(2)
    return start_server_process(folder)


def _is_pid_alive(pid):
    if not pid:
        return False
    if HAS_PSUTIL:
        try:
            p = psutil.Process(pid)
            return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


SERVER_HISTORY = {}
PROC_CACHE = {}
HISTORY_MAX = 80


def _sample_server(folder, srv):
    pid = srv.get("pid")
    if not pid:
        return
    cpu = 0.0
    mem = 0.0
    if HAS_PSUTIL:
        try:
            p = PROC_CACHE.get(pid)
            if p is None or p.pid != pid or not p.is_running():
                p = psutil.Process(pid)
                PROC_CACHE[pid] = p
            cpu = p.cpu_percent()
            mem = p.memory_info().rss / (1024 * 1024)
        except Exception:
            PROC_CACHE.pop(pid, None)
            return
    hist = SERVER_HISTORY.setdefault(folder, [])
    hist.append({"t": int(time.time()), "cpu": round(cpu, 1), "mem": round(mem, 1)})
    if len(hist) > HISTORY_MAX:
        del hist[: len(hist) - HISTORY_MAX]


def process_monitor():
    while True:
        try:
            for folder, srv in list(db["servers"].items()):
                if srv.get("status") == "Running":
                    if not _is_pid_alive(srv.get("pid")):
                        if srv.get("auto_restart", True):
                            srv["restart_count"] = srv.get("restart_count", 0) + 1
                            srv["last_restart"] = _now()
                            save_db(db)
                            restart_server(folder)
                    else:
                        _sample_server(folder, srv)
        except Exception:
            pass
        time.sleep(15)


threading.Thread(target=process_monitor, daemon=True).start()


# ----------------------------------------------------------------------
#  ديكوريترات الحماية
# ----------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if "username" not in session:
            return jsonify(success=False, message="\u063a\u064a\u0631 \u0645\u0635\u0631\u062d"), 401
        return f(*a, **k)
    return w


def admin_access():
    if is_admin(session.get("username")):
        return True
    api_key = None
    if request.is_json:
        try:
            api_key = (request.get_json(silent=True) or {}).get("api_key")
        except Exception:
            pass
    api_key = api_key or request.args.get("api_key")
    if api_key:
        uname, _ = get_user_by_api_key(api_key)
        if uname and is_admin(uname):
            return True
    return False


def owned_server(folder):
    srv = db["servers"].get(folder)
    if not srv or srv.get("owner") != session.get("username"):
        return None
    return srv


def safe_name(name):
    return name and ".." not in name and "/" not in name and "\\" not in name


# ----------------------------------------------------------------------
#  الصفحات
# ----------------------------------------------------------------------
@app.route("/")
def home():
    if "username" not in session:
        return redirect("/login")
    if is_admin(session["username"]):
        return redirect("/admin")
    return redirect("/dashboard")


@app.route("/login")
def login_page():
    if "username" in session:
        return redirect("/")
    return render_static("login.html")


@app.route("/dashboard")
def dashboard_page():
    if "username" not in session:
        return redirect("/login")
    return render_static("dashboard.html")


@app.route("/admin")
def admin_page():
    if "username" not in session or not is_admin(session["username"]):
        return redirect("/login")
    return render_static("admin.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ----------------------------------------------------------------------
#  PWA (التثبيت من المتصفح)
# ----------------------------------------------------------------------
@app.route("/manifest.webmanifest")
def pwa_manifest():
    return send_from_directory(STATIC_DIR, "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.route("/sw.js")
def pwa_service_worker():
    resp = make_response(send_from_directory(STATIC_DIR, "sw.js"))
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(STATIC_DIR, "favicon.ico")


# ----------------------------------------------------------------------
#  المصادقة
# ----------------------------------------------------------------------
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify(success=False, message="\u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0644 \u0645\u0637\u0644\u0648\u0628\u0629")
    if len(username) < 3:
        return jsonify(success=False, message="\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 3 \u0623\u062d\u0631\u0641 \u0639\u0644\u0649 \u0627\u0644\u0623\u0642\u0644")
    if len(password) < 4:
        return jsonify(success=False, message="\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 4 \u0623\u062d\u0631\u0641 \u0639\u0644\u0649 \u0627\u0644\u0623\u0642\u0644")
    if not re.match(r"^[A-Za-z0-9_.-]+$", username):
        return jsonify(success=False, message="\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u0628\u062d\u0631\u0648\u0641 \u0648\u0623\u0631\u0642\u0627\u0645 \u0641\u0642\u0637")
    with _lock:
        if any(username.lower() == u.lower() for u in db["users"]):
            return jsonify(success=False, message="\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u0645\u0648\u062c\u0648\u062f \u0628\u0627\u0644\u0641\u0639\u0644")
        db["users"][username] = {
            "password": generate_password_hash(password),
            "is_admin": False, "status": "pending", "created_at": _now(),
            "last_login": None, "plan": "free",
            "max_servers": db["plans"]["free"]["max_servers"],
            "storage_limit": db["plans"]["free"]["storage"],
            "api_key": None, "telegram_id": None,
        }
        save_db(db)
    threading.Thread(target=notify_admin, args=(
        f"\U0001f514 *\u0637\u0644\u0628 \u062d\u0633\u0627\u0628 \u062c\u062f\u064a\u062f*\n\U0001f464 `{username}`\n\U0001f4c5 {_now()}",), daemon=True).start()
    return jsonify(success=True, message="\u062a\u0645 \u0625\u0631\u0633\u0627\u0644 \u0637\u0644\u0628\u0643! \u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0645\u0648\u0627\u0641\u0642\u0629 \u0627\u0644\u0645\u0633\u0624\u0648\u0644.")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify(success=False, message="\u064a\u0631\u062c\u0649 \u0645\u0644\u0621 \u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0644")
    user = db["users"].get(username)
    if not user or not check_password_hash(user["password"], password):
        return jsonify(success=False, message="\u0628\u064a\u0627\u0646\u0627\u062a \u063a\u064a\u0631 \u0635\u062d\u064a\u062d\u0629")
    if not user.get("is_admin"):
        if user.get("status") == "pending":
            return jsonify(success=False, message="\u062d\u0633\u0627\u0628\u0643 \u0642\u064a\u062f \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629 \u0645\u0646 \u0627\u0644\u0645\u0633\u0624\u0648\u0644")
        if user.get("status") == "rejected":
            return jsonify(success=False, message="\u062a\u0645 \u0631\u0641\u0636 \u0637\u0644\u0628 \u062d\u0633\u0627\u0628\u0643")
    session.clear()
    session["username"] = username
    session.permanent = True
    user["last_login"] = _now()
    save_db(db)
    try:
        from app_pro import track_login, log_activity
        track_login(username)
        log_activity(username, "login", "تسجيل دخول ناجح")
    except Exception: pass
    return jsonify(success=True, redirect="/admin" if user.get("is_admin") else "/dashboard",
                   is_admin=bool(user.get("is_admin")))


@app.route("/api/logout", methods=["GET", "POST"])
def api_logout():
    session.clear()
    resp = make_response(jsonify(success=True))
    resp.set_cookie("session", "", expires=0)
    return resp


@app.route("/api/current_user")
def api_current_user():
    if "username" in session:
        u = db["users"].get(session["username"])
        if u:
            return jsonify(success=True, username=session["username"],
                           is_admin=bool(u.get("is_admin")), plan=u.get("plan", "free"),
                           api_key=u.get("api_key"), telegram_id=u.get("telegram_id"))
    return jsonify(success=False)


# ----------------------------------------------------------------------
#  API Key + Telegram
# ----------------------------------------------------------------------
@app.route("/api/create_api_key", methods=["POST"])
@login_required
def create_api_key():
    key = generate_api_key()
    db["users"][session["username"]]["api_key"] = key
    save_db(db)
    return jsonify(success=True, api_key=key, message="\u062a\u0645 \u0625\u0646\u0634\u0627\u0621 \u0645\u0641\u062a\u0627\u062d API")


@app.route("/api/link_telegram", methods=["POST"])
@login_required
def link_telegram():
    tg = str((request.get_json(silent=True) or {}).get("telegram_id", "")).strip()
    if not tg:
        return jsonify(success=False, message="\u0645\u0639\u0631\u0641 \u062a\u064a\u0644\u064a\u062c\u0631\u0627\u0645 \u0645\u0637\u0644\u0648\u0628")
    db["users"][session["username"]]["telegram_id"] = tg
    save_db(db)
    return jsonify(success=True, message="\u062a\u0645 \u0631\u0628\u0637 \u062d\u0633\u0627\u0628 \u0627\u0644\u062a\u064a\u0644\u064a\u062c\u0631\u0627\u0645")


@app.route("/api/user/change-password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    current = (data.get("current") or "").strip()
    new = (data.get("new") or "").strip()
    u = db["users"].get(session["username"])
    if not u:
        return jsonify(success=False, message="\u0645\u0633\u062a\u062e\u062f\u0645 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")
    if not check_password_hash(u["password"], current):
        return jsonify(success=False, message="\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0627\u0644\u062d\u0627\u0644\u064a\u0629 \u063a\u064a\u0631 \u0635\u062d\u064a\u062d\u0629")
    if len(new) < 4:
        return jsonify(success=False, message="\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0627\u0644\u062c\u062f\u064a\u062f\u0629 \u0642\u0635\u064a\u0631\u0629 (4 \u0623\u062d\u0631\u0641 \u0639\u0644\u0649 \u0627\u0644\u0623\u0642\u0644)")
    u["password"] = generate_password_hash(new)
    save_db(db)
    return jsonify(success=True, message="\u2705 \u062a\u0645 \u062a\u063a\u064a\u064a\u0631 \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0628\u0646\u062c\u0627\u062d")


# ----------------------------------------------------------------------
#  الخطط
# ----------------------------------------------------------------------
@app.route("/api/plans")
def get_plans():
    return jsonify(success=True, plans=db.get("plans", {}))


@app.route("/api/user/upgrade", methods=["POST"])
@login_required
def upgrade_plan():
    plan_id = (request.get_json(silent=True) or {}).get("plan_id")
    if not plan_id or plan_id not in db.get("plans", {}):
        return jsonify(success=False, message="\u062e\u0637\u0629 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f\u0629")
    plan = db["plans"][plan_id]
    u = db["users"][session["username"]]
    u["plan"] = plan_id
    u["max_servers"] = plan["max_servers"]
    u["storage_limit"] = plan["storage"]
    save_db(db)
    notify_admin(f"\U0001f48e *\u062a\u0631\u0642\u064a\u0629*\n\U0001f464 `{session['username']}` \u2192 {plan['name']}")
    return jsonify(success=True, message=f"\u2705 \u062a\u0645 \u0627\u0644\u062a\u0631\u0642\u064a\u0629 \u0625\u0644\u0649 {plan['name']}")


@app.route("/api/payment/info")
@login_required
def payment_info():
    return jsonify(success=True, vodafone=PAY_VODAFONE, instapay=PAY_INSTAPAY, note=PAY_NOTE)


@app.route("/api/user/request-upgrade", methods=["POST"])
@login_required
def request_upgrade():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")
    method = (data.get("method") or "").strip()
    if not plan_id or plan_id not in db.get("plans", {}):
        return jsonify(success=False, message="\u062e\u0637\u0629 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f\u0629")
    plan = db["plans"][plan_id]
    req = {
        "id": secrets.token_hex(6),
        "username": session["username"],
        "plan_id": plan_id,
        "plan_name": plan.get("name", plan_id),
        "price": plan.get("price", 0),
        "method": method,
        "status": "pending",
        "created_at": _now(),
    }
    db.setdefault("payments", []).insert(0, req)
    save_db(db)
    notify_admin(f"\U0001f4b3 *\u0637\u0644\u0628 \u062a\u0631\u0642\u064a\u0629 \u062c\u062f\u064a\u062f*\n\U0001f464 `{session['username']}`\n\U0001f48e {plan.get('name')}\n\U0001f4b0 ${plan.get('price')}\n\U0001f4b3 {method or chr(8212)}")
    return jsonify(success=True, message="\u2705 \u062a\u0645 \u0625\u0631\u0633\u0627\u0644 \u0627\u0644\u0637\u0644\u0628\u060c \u0647\u064a\u062a\u0641\u0639\u0651\u0644 \u0628\u0639\u062f \u062a\u0623\u0643\u064a\u062f \u0627\u0644\u062f\u0641\u0639")


@app.route("/api/admin/payments")
def admin_payments():
    if not admin_access():
        return jsonify(success=False), 403
    return jsonify(success=True, payments=db.get("payments", []))


@app.route("/api/admin/payment-action", methods=["POST"])
def admin_payment_action():
    if not admin_access():
        return jsonify(success=False), 403
    data = request.get_json(silent=True) or {}
    pid = data.get("id")
    action = data.get("action")
    pay = next((p for p in db.get("payments", []) if p.get("id") == pid), None)
    if not pay:
        return jsonify(success=False, message="\u0627\u0644\u0637\u0644\u0628 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")
    if action == "approve":
        u = db["users"].get(pay["username"])
        plan = db["plans"].get(pay["plan_id"])
        if u and plan:
            u["plan"] = pay["plan_id"]
            u["max_servers"] = plan["max_servers"]
            u["storage_limit"] = plan["storage"]
        pay["status"] = "approved"
        notify_admin(f"\u2705 \u062a\u0645 \u062a\u0641\u0639\u064a\u0644 \u062a\u0631\u0642\u064a\u0629 `{pay['username']}` \u2192 {pay['plan_name']}")
    elif action == "reject":
        pay["status"] = "rejected"
    else:
        return jsonify(success=False, message="\u0625\u062c\u0631\u0627\u0621 \u063a\u064a\u0631 \u0635\u0627\u0644\u062d")
    save_db(db)
    return jsonify(success=True, message="\u062a\u0645")


@app.route("/api/admin/add-plan", methods=["POST"])
def admin_add_plan():
    if not admin_access():
        return jsonify(success=False), 403
    data = request.get_json(silent=True) or {}
    pid = (data.get("id") or "").strip()
    if not pid:
        return jsonify(success=False, message="\u0645\u0639\u0631\u0641 \u0627\u0644\u062e\u0637\u0629 \u0645\u0637\u0644\u0648\u0628")
    db["plans"][pid] = {
        "name": data.get("name", pid),
        "storage": int(data.get("storage", 512)),
        "ram": int(data.get("ram", 256)),
        "cpu": float(data.get("cpu", 0.5)),
        "max_servers": int(data.get("max_servers", 2)),
        "price": float(data.get("price", 0)),
    }
    save_db(db)
    return jsonify(success=True, message="\u2705 \u062a\u0645\u062a \u0625\u0636\u0627\u0641\u0629 \u0627\u0644\u062e\u0637\u0629")


# ----------------------------------------------------------------------
#  إدارة المستخدمين (أدمن)
# ----------------------------------------------------------------------
def _user_public(uname, udata):
    return {
        "username": uname, "is_admin": udata.get("is_admin", False),
        "status": udata.get("status", "approved"), "created_at": udata.get("created_at"),
        "last_login": udata.get("last_login"), "max_servers": udata.get("max_servers", 2),
        "plan": udata.get("plan", "free"), "telegram_id": udata.get("telegram_id"),
        "api_key": udata.get("api_key"), "storage_limit": udata.get("storage_limit", 512),
    }


@app.route("/api/admin/users")
def admin_users():
    if not admin_access():
        return jsonify(success=False), 403
    return jsonify(success=True, users=[_user_public(u, d) for u, d in db["users"].items()])


@app.route("/api/admin/pending")
def admin_pending():
    if not admin_access():
        return jsonify(success=False), 403
    reqs = [{"username": u, "created_at": d.get("created_at")}
            for u, d in db["users"].items() if d.get("status") == "pending"]
    return jsonify(success=True, requests=reqs)


@app.route("/api/admin/approve", methods=["POST"])
def admin_approve():
    if not admin_access():
        return jsonify(success=False), 403
    uname = (request.get_json(silent=True) or {}).get("username")
    u = db["users"].get(uname)
    if not u:
        return jsonify(success=False, message="\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")
    u["status"] = "approved"
    save_db(db)
    os.makedirs(os.path.join(USERS_DIR, uname, "SERVERS"), exist_ok=True)
    return jsonify(success=True, message=f"\u2705 \u062a\u0645 \u0642\u0628\u0648\u0644 {uname}")


@app.route("/api/admin/reject", methods=["POST"])
def admin_reject():
    if not admin_access():
        return jsonify(success=False), 403
    uname = (request.get_json(silent=True) or {}).get("username")
    u = db["users"].get(uname)
    if not u:
        return jsonify(success=False, message="\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")
    u["status"] = "rejected"
    save_db(db)
    return jsonify(success=True, message=f"\U0001f6ab \u062a\u0645 \u0631\u0641\u0636 {uname}")


@app.route("/api/admin/create-user", methods=["POST"])
def admin_create_user():
    if not admin_access():
        return jsonify(success=False), 403
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify(success=False, message="\u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0644 \u0645\u0637\u0644\u0648\u0628\u0629")
    if username in db["users"]:
        return jsonify(success=False, message="\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u0645\u0648\u062c\u0648\u062f")
    db["users"][username] = {
        "password": generate_password_hash(password), "is_admin": False,
        "status": "approved", "created_at": _now(), "last_login": None, "plan": "free",
        "max_servers": int(data.get("max_servers", 2)),
        "storage_limit": int(data.get("storage_limit", 512)),
        "api_key": None, "telegram_id": None,
    }
    save_db(db)
    os.makedirs(os.path.join(USERS_DIR, username, "SERVERS"), exist_ok=True)
    return jsonify(success=True, message="\u2705 \u062a\u0645 \u0625\u0646\u0634\u0627\u0621 \u0627\u0644\u062d\u0633\u0627\u0628")


@app.route("/api/admin/update-user", methods=["POST"])
def admin_update_user():
    if not admin_access():
        return jsonify(success=False), 403
    data = request.get_json(silent=True) or {}
    uname = (data.get("username") or "").strip()
    u = db["users"].get(uname)
    if not u:
        return jsonify(success=False, message="\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")
    if "max_servers" in data: u["max_servers"] = int(data["max_servers"])
    if "storage_limit" in data: u["storage_limit"] = int(data["storage_limit"])
    if "is_admin" in data: u["is_admin"] = bool(data["is_admin"])
    if "plan" in data and data["plan"] in db["plans"]: u["plan"] = data["plan"]
    save_db(db)
    return jsonify(success=True, message=f"\u2705 \u062a\u0645 \u062a\u062d\u062f\u064a\u062b {uname}")


@app.route("/api/admin/delete-user", methods=["POST"])
def admin_delete_user():
    if not admin_access():
        return jsonify(success=False), 403
    uname = (request.get_json(silent=True) or {}).get("username", "").strip()
    if not uname or uname == ADMIN_USER:
        return jsonify(success=False, message="\u0644\u0627 \u064a\u0645\u0643\u0646 \u062d\u0630\u0641 \u0647\u0630\u0627 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645")
    if uname in db["users"]:
        for fid in [f for f, s in db["servers"].items() if s.get("owner") == uname]:
            stop_server_process(fid)
            shutil.rmtree(db["servers"][fid]["path"], ignore_errors=True)
            del db["servers"][fid]
        shutil.rmtree(os.path.join(USERS_DIR, uname), ignore_errors=True)
        del db["users"][uname]
        save_db(db)
        return jsonify(success=True, message=f"\U0001f5d1 \u062a\u0645 \u062d\u0630\u0641 {uname}")
    return jsonify(success=False, message="\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")


# ----------------------------------------------------------------------
#  النظام
# ----------------------------------------------------------------------
def groq_chat(messages, model="smart", max_tokens=1100, temperature=0.4):
    if not GROQ_API_KEY:
        return None, "GROQ_API_KEY غير مضبوط — ضِف المفتاح في متغيرات البيئة."
    try:
        r = requests.post(
            GROQ_API_URL,
            headers={"Authorization": "Bearer " + GROQ_API_KEY, "Content-Type": "application/json"},
            json={
                "model": GROQ_MODELS.get(model, GROQ_MODELS["smart"]),
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=45,
        )
        if r.status_code != 200:
            return None, "خطأ من Groq (%s)" % r.status_code
        data = r.json()
        return data["choices"][0]["message"]["content"], None
    except Exception as e:
        return None, "تعذّر الاتصال بـ Groq: %s" % e


@app.route("/api/ai", methods=["POST"])
@login_required
def ai_endpoint():
    body = request.get_json(force=True, silent=True) or {}
    mode = body.get("mode", "chat")
    model = body.get("model", "smart")
    text = (body.get("text") or "").strip()
    code = body.get("code") or ""
    logs = body.get("logs") or ""
    history = body.get("history") or []

    if mode == "chat":
        if not text:
            return jsonify(success=False, message="اكتب رسالة أولًا")
        sys_p = ("أنت مساعد ذكي داخل لوحة استضافة ��سمها BATMAN Dev. ساعد المستخدم في "
                 "البرمجة والبوتات والاستضافة. رد باختصار وبنفس لغة المستخدم (عربي افتراضيًا).")
        messages = [{"role": "system", "content": sys_p}]
        for h in history[-8:]:
            role = "assistant" if h.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": str(h.get("content", ""))[:4000]})
        messages.append({"role": "user", "content": text})
    elif mode == "diagnose":
        if not logs.strip():
            return jsonify(success=False, message="لا توجد أخطاء لتشخيصها")
        model = "smart"
        sys_p = ("أنت خبير DevOps وبايثون/نود. حلّل لوج الأخطاء واشرح السبب بالعربي بإيجاز، "
                 "ثم اقترح الحل العملي مع سطر/أسطر الكود أو الأمر اللازم في نقاط واضحة.")
        messages = [{"role": "system", "content": sys_p},
                    {"role": "user", "content": "لوج الأخطاء:\n" + logs[:6000]}]
    elif mode == "code":
        action = body.get("action", "explain")
        prompts = {
            "explain": "اشرح الكود التالي بالعربي خطوة بخطوة باختصار.",
            "fix": "صحّح أخطاء الكود التالي وأعد الكود المصحَّح كامل داخل بلوك code، ثم اشرح ما غيّرته باختصار.",
            "feature": "أضِف الميزة المطلوبة للكود التالي وأعد الكود الكامل داخل بلوك code ثم اشرح باختصار.",
        }
        instr = prompts.get(action, prompts["explain"])
        if text:
            instr += "\nالمطلوب من المستخدم: " + text
        messages = [{"role": "system", "content": "أنت مساعد برمجة محترف. رد بالعربي والكود داخل بلوكات code."},
                    {"role": "user", "content": instr + "\n\nالكود:\n```\n" + code[:7000] + "\n```"}]
    else:
        return jsonify(success=False, message="وضع غير معروف")

    reply, err = groq_chat(messages, model=model)
    if err:
        return jsonify(success=False, message=err)
    return jsonify(success=True, reply=reply)


@app.route("/api/system/metrics")
def metrics():
    if HAS_PSUTIL:
        try:
            return jsonify(cpu=psutil.cpu_percent(), memory=psutil.virtual_memory().percent,
                           disk=psutil.disk_usage("/").percent)
        except Exception:
            pass
    return jsonify(cpu=0, memory=0, disk=0)


@app.route("/api/ping", methods=["GET", "POST"])
def ping():
    return jsonify(status="pong", timestamp=str(datetime.now()))


# ----------------------------------------------------------------------
#  السيرفرات
# ----------------------------------------------------------------------
def _dir_size_mb(path):
    total = 0
    if os.path.exists(path):
        for root, _, files in os.walk(path):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except Exception:
                    pass
    return round(total / (1024 * 1024), 2)


@app.route("/api/servers")
@login_required
def list_servers():
    uname = session["username"]
    out = []
    total_disk = 0.0
    for folder, srv in db["servers"].items():
        if srv.get("owner") == uname:
            used = _dir_size_mb(srv["path"])
            total_disk += used
            out.append({
                "folder": folder, "title": srv["name"],
                "subtitle": f"\u0633\u064a\u0631\u0641\u0631 {srv.get('type', 'Python')}",
                "type": srv.get("type", "Python"), "startup_file": srv.get("startup_file", ""),
                "status": srv.get("status", "Stopped"),
                "uptime": uptime_str(srv.get("start_time")) if srv.get("status") == "Running" else "0 \u062b\u0627\u0646\u064a\u0629",
                "port": srv.get("port", "N/A"), "plan": srv.get("plan", "free"),
                "disk_used": used, "ram_limit": srv.get("ram_limit", 256),
                "cpu_limit": srv.get("cpu_limit", 0.5),
                "auto_restart": srv.get("auto_restart", True),
                "restart_count": srv.get("restart_count", 0),
                "public": srv.get("public", False),
                "public_url": (f"/v/{srv['public_token']}/" if srv.get("public") and srv.get("public_token") else ""),
            })
    u = db["users"].get(uname, {})
    return jsonify(success=True, servers=out, stats={
        "used": len(out), "total": u.get("max_servers", 2),
        "disk_used": round(total_disk, 2), "disk_total": u.get("storage_limit", 512),
        "plan": u.get("plan", "free"),
    })


def _create_server(username, name, server_type):
    user = db["users"].get(username)
    count = len([s for s in db["servers"].values() if s.get("owner") == username])
    if count >= user.get("max_servers", 2):
        return None, f"\u0648\u0635\u0644\u062a \u0644\u0644\u062d\u062f \u0627\u0644\u0623\u0642\u0635\u0649 ({user.get('max_servers', 2)})"
    if server_type not in ("Python", "Node.js", "PHP", "HTML"):
        server_type = "Python"
    plan = db["plans"].get(user.get("plan", "free"), db["plans"]["free"])
    folder = f"{username}_{re.sub(r'[^a-zA-Z0-9]', '', name)}_{int(time.time())}"
    path = os.path.join(user_servers_dir(username), folder)
    os.makedirs(path, exist_ok=True)
    db["servers"][folder] = {
        "name": name, "owner": username, "path": path, "type": server_type,
        "status": "Stopped", "created_at": _now(), "startup_file": "", "pid": None,
        "port": get_assigned_port(), "plan": user.get("plan", "free"),
        "storage_limit": plan["storage"], "ram_limit": plan["ram"], "cpu_limit": plan["cpu"],
        "auto_restart": True, "restart_count": 0, "last_restart": None,
    }
    save_db(db)
    return folder, "ok"


@app.route("/api/server/add", methods=["POST"])
@login_required
def add_server():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(success=False, message="\u0627\u0644\u0631\u062c\u0627\u0621 \u0625\u062f\u062e\u0627\u0644 \u0627\u0633\u0645 \u0644\u0644\u0633\u064a\u0631\u0641\u0631")
    folder, msg = _create_server(session["username"], name, data.get("server_type", "Python"))
    if not folder:
        return jsonify(success=False, message=msg)
    return jsonify(success=True, message=f"\u2705 \u062a\u0645 \u0625\u0646\u0634\u0627\u0621 \u0627\u0644\u062e\u0627\u062f\u0645 {name}", folder=folder)


@app.route("/api/server/action/<folder>/<action>", methods=["POST"])
@login_required
def server_action(folder, action):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False, message="\u063a\u064a\u0631 \u0645\u0635\u0631\u062d")
    if action == "toggle-restart":
        srv["auto_restart"] = not srv.get("auto_restart", True)
        save_db(db)
        return jsonify(success=True, auto_restart=srv["auto_restart"],
                       message=("✅ التشغيل التلقائي مُفعّل" if srv["auto_restart"] else "⏹️ التشغيل التلقائي متوقف"))
    if action == "start":
        if srv.get("status") == "Running":
            return jsonify(success=False, message="\u0627\u0644\u062e\u0627\u062f\u0645 \u064a\u0639\u0645\u0644 \u0628\u0627\u0644\u0641\u0639\u0644")
        ok, msg = start_server_process(folder)
        return jsonify(success=ok, message=msg)
    if action == "stop":
        stop_server_process(folder)
        return jsonify(success=True, message="\U0001f6d1 \u062a\u0645 \u0627\u0644\u0625\u064a\u0642\u0627\u0641")
    if action == "restart":
        restart_server(folder)
        return jsonify(success=True, message="\U0001f504 \u062a\u0645 \u0627\u0644\u0625\u0639\u0627\u062f\u0629")
    if action == "delete":
        stop_server_process(folder)
        shutil.rmtree(srv["path"], ignore_errors=True)
        del db["servers"][folder]
        save_db(db)
        return jsonify(success=True, message="\U0001f5d1 \u062a\u0645 \u0627\u0644\u062d\u0630\u0641")
    return jsonify(success=False, message="\u0625\u062c\u0631\u0627\u0621 \u063a\u064a\u0631 \u0645\u0639\u0631\u0648\u0641")


def _read_tail(path, n):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return "\n".join(f.read().split("\n")[-n:])
        except Exception:
            pass
    return ""


@app.route("/api/server/stats/<folder>")
@login_required
def server_stats(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False)
    status = srv.get("status", "Stopped")
    mem = "0 MB"
    if HAS_PSUTIL and srv.get("pid") and status == "Running":
        try:
            mem = f"{psutil.Process(srv['pid']).memory_info().rss / (1024*1024):.1f} MB"
        except Exception:
            pass
    return jsonify(success=True, status=status,
                   logs=_read_tail(os.path.join(srv["path"], "out.log"), 500) or "\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u062e\u0631\u062c\u0627\u062a \u0628\u0639\u062f",
                   errors=_read_tail(os.path.join(srv["path"], "errors.log"), 100),
                   mem=mem, uptime=uptime_str(srv.get("start_time")) if status == "Running" else "0 \u062b\u0627\u0646\u064a\u0629",
                   port=srv.get("port", "--"), ip=get_public_ip(), type=srv.get("type", "Python"))


@app.route("/api/server/history/<folder>")
@login_required
def server_history(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False, history=[])
    return jsonify(success=True, history=SERVER_HISTORY.get(folder, []))


@app.route("/api/server/set-startup/<folder>", methods=["POST"])
@login_required
def set_startup(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False)
    fn = (request.get_json(silent=True) or {}).get("filename", "").strip()
    if not safe_name(fn) or not os.path.exists(os.path.join(srv["path"], fn)):
        return jsonify(success=False, message="\u0627\u0644\u0645\u0644\u0641 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")
    srv["startup_file"] = fn
    save_db(db)
    return jsonify(success=True, message=f"\u2705 \u062a\u0645 \u062a\u0639\u064a\u064a\u0646 {fn}")


@app.route("/api/server/install/<folder>", methods=["POST"])
@login_required
def server_install(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False)
    threading.Thread(target=auto_install_deps,
                     args=(srv["path"], srv.get("type", "Python"), os.path.join(srv["path"], "out.log")),
                     daemon=True).start()
    return jsonify(success=True, message="\U0001f4e6 \u0628\u062f\u0623 \u0627\u0644\u062a\u062b\u0628\u064a\u062a")


# ----------------------------------------------------------------------
#  الملفات
# ----------------------------------------------------------------------
@app.route("/api/files/list/<folder>")
@login_required
def files_list(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify([])
    out = []
    try:
        for fn in os.listdir(srv["path"]):
            if fn in ("out.log", "errors.log"):
                continue
            fp = os.path.join(srv["path"], fn)
            st = os.stat(fp)
            sz = st.st_size
            s = f"{sz} B" if sz < 1024 else (f"{sz/1024:.1f} KB" if sz < 1048576 else f"{sz/1048576:.1f} MB")
            out.append({"name": fn, "size": s, "is_dir": os.path.isdir(fp),
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "is_zip": fn.lower().endswith(".zip")})
    except Exception:
        pass
    return jsonify(sorted(out, key=lambda x: (not x["is_dir"], x["name"].lower())))


@app.route("/api/files/content/<folder>/<path:filename>")
@login_required
def file_content(folder, filename):
    srv = owned_server(folder)
    if not srv or ".." in filename:
        return jsonify(content="")
    fp = os.path.join(srv["path"], filename)
    if not os.path.exists(fp) or os.path.isdir(fp):
        return jsonify(content="")
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            return jsonify(content=f.read())
    except Exception:
        return jsonify(content="[\u0645\u0644\u0641 \u062b\u0646\u0627\u0626\u064a]")


@app.route("/api/files/raw/<folder>/<path:filename>")
@login_required
def file_raw(folder, filename):
    from flask import send_file
    srv = owned_server(folder)
    if not srv or ".." in filename:
        return ("", 404)
    fp = os.path.join(srv["path"], filename)
    if not os.path.exists(fp) or os.path.isdir(fp):
        return ("", 404)
    return send_file(fp)


@app.route("/api/files/save/<folder>/<path:filename>", methods=["POST"])
@login_required
def file_save(folder, filename):
    srv = owned_server(folder)
    if not srv or ".." in filename:
        return jsonify(success=False, message="\u0627\u0633\u0645 \u063a\u064a\u0631 \u0635\u0627\u0644\u062d")
    try:
        with open(os.path.join(srv["path"], filename), "w", encoding="utf-8") as f:
            f.write((request.get_json(silent=True) or {}).get("content", ""))
        return jsonify(success=True, message="\u2705 \u062a\u0645 \u0627\u0644\u062d\u0641\u0638")
    except Exception as e:
        return jsonify(success=False, message=str(e))


@app.route("/api/files/upload/<folder>", methods=["POST"])
@login_required
def files_upload(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False)
    files = request.files.getlist("files[]")
    if not files:
        return jsonify(success=False, message="\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0644\u0641\u0627\u062a")
    uploaded = 0
    extracted = 0
    for f in files:
        if not f or not f.filename or ".." in f.filename:
            continue
        try:
            dest = os.path.join(srv["path"], os.path.basename(f.filename))
            f.save(dest)
            uploaded += 1
            if dest.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(dest, "r") as zf:
                        if all(not (m.startswith("/") or ".." in m) for m in zf.namelist()):
                            zf.extractall(srv["path"])
                            extracted += 1
                            os.remove(dest)
                except Exception:
                    pass
        except Exception:
            pass
    if uploaded:
        threading.Thread(target=auto_install_deps,
                         args=(srv["path"], srv.get("type", "Python"), os.path.join(srv["path"], "out.log")),
                         daemon=True).start()
        msg = f"\u2705 \u062a\u0645 \u0631\u0641\u0639 {uploaded} \u0645\u0644\u0641"
        if extracted:
            msg += f" \u0648\u062a\u0645 \u0641\u0643 {extracted} \u0623\u0631\u0634\u064a\u0641 ZIP \u062a\u0644\u0642\u0627\u0626\u064a\u064b\u0627"
        return jsonify(success=True, message=msg)
    return jsonify(success=False, message="\u0641\u0634\u0644 \u0627\u0644\u0631\u0641\u0639")


@app.route("/api/files/rename/<folder>", methods=["POST"])
@login_required
def file_rename(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False)
    data = request.get_json(silent=True) or {}
    old = (data.get("old_name") or "").strip()
    new = (data.get("new_name") or "").strip()
    if not safe_name(old) or not safe_name(new):
        return jsonify(success=False, message="\u0627\u0633\u0645 \u063a\u064a\u0631 \u0635\u0627\u0644\u062d")
    op = os.path.join(srv["path"], old); np = os.path.join(srv["path"], new)
    if not os.path.exists(op):
        return jsonify(success=False, message="\u0627\u0644\u0645\u0644\u0641 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")
    if os.path.exists(np):
        return jsonify(success=False, message="\u064a\u0648\u062c\u062f \u0645\u0644\u0641 \u0628\u0646\u0641\u0633 \u0627\u0644\u0627\u0633\u0645")
    os.rename(op, np)
    if srv.get("startup_file") == old:
        srv["startup_file"] = new; save_db(db)
    return jsonify(success=True, message=f"\u2705 \u062a\u0645\u062a \u0627\u0644\u0625\u0639\u0627\u062f\u0629 \u0625\u0644\u0649 {new}")


@app.route("/api/files/unzip/<folder>/<path:filename>", methods=["POST"])
@login_required
def file_unzip(folder, filename):
    srv = owned_server(folder)
    if not srv or not filename.lower().endswith(".zip") or ".." in filename:
        return jsonify(success=False, message="\u0645\u0644\u0641 \u063a\u064a\u0631 \u0635\u0627\u0644\u062d")
    zp = os.path.join(srv["path"], filename)
    if not os.path.exists(zp):
        return jsonify(success=False, message="\u0627\u0644\u0645\u0644\u0641 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f")
    try:
        with zipfile.ZipFile(zp, "r") as zf:
            for m in zf.namelist():
                if m.startswith("/") or ".." in m:
                    return jsonify(success=False, message="ZIP \u063a\u064a\u0631 \u0622\u0645\u0646")
            zf.extractall(srv["path"])
        return jsonify(success=True, message=f"\u2705 \u062a\u0645 \u0641\u0643 \u0636\u063a\u0637 {filename}")
    except zipfile.BadZipFile:
        return jsonify(success=False, message="ZIP \u063a\u064a\u0631 \u0635\u0627\u0644\u062d")


@app.route("/api/files/delete/<folder>", methods=["POST"])
@login_required
def files_delete(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False)
    names = (request.get_json(silent=True) or {}).get("names", [])
    if isinstance(names, str):
        names = [names]
    deleted = 0
    for name in names:
        if not safe_name(name):
            continue
        fp = os.path.join(srv["path"], name)
        try:
            if os.path.isdir(fp):
                shutil.rmtree(fp)
            elif os.path.exists(fp):
                os.remove(fp)
            deleted += 1
        except Exception:
            pass
    return jsonify(success=deleted > 0, message=f"\U0001f5d1 \u062a\u0645 \u062d\u0630\u0641 {deleted} \u0639\u0646\u0635\u0631")


@app.route("/api/files/create/<folder>", methods=["POST"])
@login_required
def file_create(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False)
    data = request.get_json(silent=True) or {}
    fn = (data.get("filename") or "").strip()
    if not safe_name(fn):
        return jsonify(success=False, message="\u0627\u0633\u0645 \u063a\u064a\u0631 \u0635\u0627\u0644\u062d")
    try:
        with open(os.path.join(srv["path"], fn), "w", encoding="utf-8") as f:
            f.write(data.get("content", ""))
        return jsonify(success=True, message=f"\u2705 \u062a\u0645 \u0625\u0646\u0634\u0627\u0621 {fn}")
    except Exception as e:
        return jsonify(success=False, message=str(e))


# ----------------------------------------------------------------------
#  \u0645\u0639\u0627\u064a\u0646\u0629 \u0645\u0648\u0627\u0642\u0639 PHP / HTML (\u0628\u0631\u0648\u0643\u0633\u064a)
# ----------------------------------------------------------------------
def _proxy_to_server(srv, sub):
    if srv.get("type") != "HTML" or srv.get("status") != "Running" or not srv.get("port"):
        return ("<h3 style='font-family:sans-serif;text-align:center;margin-top:40px'>\u26a0\ufe0f \u0627\u0644\u0633\u064a\u0631\u0641\u0631 \u0645\u062a\u0648\u0642\u0641 \u062d\u0627\u0644\u064a\u064b\u0627.</h3>", 503)
    target = f"http://127.0.0.1:{srv['port']}/{sub}"
    try:
        fwd = {k: v for k, v in request.headers if k.lower() not in ("host", "content-length")}
        resp = requests.request(request.method, target, params=request.args,
                                data=request.get_data(), headers=fwd,
                                cookies=request.cookies, allow_redirects=False, timeout=30)
    except Exception as e:
        return (f"<h3 style='font-family:sans-serif;text-align:center;margin-top:40px'>\u062a\u0639\u0630\u0651\u0631 \u0627\u0644\u0648\u0635\u0648\u0644 \u0644\u0644\u0633\u064a\u0631\u0641\u0631: {e}</h3>", 502)
    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
    return (resp.content, resp.status_code, headers)


@app.route("/p/<folder>/", defaults={"sub": ""}, methods=["GET", "POST", "HEAD"])
@app.route("/p/<folder>/<path:sub>", methods=["GET", "POST", "HEAD"])
@login_required
def preview_proxy(folder, sub):
    srv = owned_server(folder)
    if not srv:
        return ("\u063a\u064a\u0631 \u0645\u0635\u0631\u062d", 403)
    return _proxy_to_server(srv, sub)


def _find_public_server(token):
    if not token:
        return None
    for srv in db["servers"].values():
        if srv.get("public") and srv.get("public_token") == token:
            return srv
    return None


@app.route("/v/<token>/", defaults={"sub": ""}, methods=["GET", "POST", "HEAD"])
@app.route("/v/<token>/<path:sub>", methods=["GET", "POST", "HEAD"])
def public_site(token, sub):
    srv = _find_public_server(token)
    if not srv:
        return ("<h3 style='font-family:sans-serif;text-align:center;margin-top:40px'>\u26d4 \u0627\u0644\u0631\u0627\u0628\u0637 \u063a\u064a\u0631 \u0645\u062a\u0627\u062d \u0623\u0648 \u0645\u0648\u0642\u0648\u0641.</h3>", 404)
    return _proxy_to_server(srv, sub)


@app.route("/api/server/public/<folder>", methods=["POST"])
@login_required
def toggle_public(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False, message="\u063a\u064a\u0631 \u0645\u0635\u0631\u062d")
    if srv.get("type") != "HTML":
        return jsonify(success=False, message="\u0627\u0644\u0631\u0627\u0628\u0637 \u0627\u0644\u0639\u0627\u0645 \u0645\u062a\u0627\u062d \u0644\u0645\u0648\u0627\u0642\u0639 HTML \u0641\u0642\u0637")
    data = request.get_json(silent=True) or {}
    enable = data.get("enable")
    srv["public"] = (not srv.get("public", False)) if enable is None else bool(enable)
    if srv["public"] and not srv.get("public_token"):
        srv["public_token"] = secrets.token_urlsafe(9)
    save_db(db)
    url = f"/v/{srv['public_token']}/" if srv["public"] else ""
    return jsonify(success=True, public=srv["public"], url=url,
                   message=("\u2705 \u062a\u0645 \u062a\u0641\u0639\u064a\u0644 \u0627\u0644\u0631\u0627\u0628\u0637 \u0627\u0644\u0639\u0627\u0645" if srv["public"] else "\u23f9\ufe0f \u062a\u0645 \u0625\u064a\u0642\u0627\u0641 \u0627\u0644\u0631\u0627\u0628\u0637 \u0627\u0644\u0639\u0627\u0645"))


# ----------------------------------------------------------------------
#  API البوت (عبر API Key)
# ----------------------------------------------------------------------
def _bot_user(req_data):
    api_key = (req_data or {}).get("api_key") or request.args.get("api_key")
    return get_user_by_api_key(api_key)


@app.route("/api/bot/verify", methods=["POST"])
def bot_verify():
    uname, user = get_user_by_api_key((request.get_json(silent=True) or {}).get("api_key"))
    if not uname:
        return jsonify(success=False, message="API Key \u063a\u064a\u0631 \u0635\u0627\u0644\u062d")
    return jsonify(success=True, username=uname, is_admin=is_admin(uname),
                   max_servers=user.get("max_servers", 2))


@app.route("/api/bot/servers")
def bot_servers():
    uname, _ = get_user_by_api_key(request.args.get("api_key"))
    if not uname:
        return jsonify(success=False, message="API Key \u063a\u064a\u0631 \u0635\u0627\u0644\u062d"), 401
    out = [{"folder": f, "title": s["name"], "status": s.get("status", "Stopped"),
            "uptime": uptime_str(s.get("start_time")) if s.get("status") == "Running" else "0 \u062b\u0627\u0646\u064a\u0629",
            "port": s.get("port", "N/A"), "type": s.get("type", "Python")}
           for f, s in db["servers"].items() if s.get("owner") == uname]
    return jsonify(success=True, servers=out)


@app.route("/api/bot/server/action", methods=["POST"])
def bot_server_action():
    data = request.get_json(silent=True) or {}
    uname, _ = get_user_by_api_key(data.get("api_key"))
    folder = data.get("folder"); action = data.get("action")
    if not uname:
        return jsonify(success=False, message="API Key \u063a\u064a\u0631 \u0635\u0627\u0644\u062d"), 401
    srv = db["servers"].get(folder)
    if not srv or srv.get("owner") != uname:
        return jsonify(success=False, message="\u063a\u064a\u0631 \u0645\u0635\u0631\u062d"), 403
    if action == "start":
        ok, msg = start_server_process(folder); return jsonify(success=ok, message=msg)
    if action == "stop":
        stop_server_process(folder); return jsonify(success=True, message="\U0001f6d1 \u062a\u0645 \u0627\u0644\u0625\u064a\u0642\u0627\u0641")
    if action == "restart":
        restart_server(folder); return jsonify(success=True, message="\U0001f504 \u062a\u0645 \u0627\u0644\u0625\u0639\u0627\u062f\u0629")
    if action == "delete":
        stop_server_process(folder); shutil.rmtree(srv["path"], ignore_errors=True)
        del db["servers"][folder]; save_db(db); return jsonify(success=True, message="\U0001f5d1 \u062a\u0645 \u0627\u0644\u062d\u0630\u0641")
    return jsonify(success=False, message="\u0625\u062c\u0631\u0627\u0621 \u063a\u064a\u0631 \u0645\u0639\u0631\u0648\u0641")


@app.route("/api/bot/console")
def bot_console():
    uname, _ = get_user_by_api_key(request.args.get("api_key"))
    folder = request.args.get("folder")
    if not uname:
        return jsonify(success=False), 401
    srv = db["servers"].get(folder)
    if not srv or srv.get("owner") != uname:
        return jsonify(success=False), 403
    return jsonify(success=True, logs=_read_tail(os.path.join(srv["path"], "out.log"), 500) or "\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u062e\u0631\u062c\u0627\u062a")


@app.route("/api/bot/errors")
def bot_errors():
    uname, _ = get_user_by_api_key(request.args.get("api_key"))
    folder = request.args.get("folder")
    if not uname:
        return jsonify(success=False), 401
    srv = db["servers"].get(folder)
    if not srv or srv.get("owner") != uname:
        return jsonify(success=False), 403
    return jsonify(success=True, errors=_read_tail(os.path.join(srv["path"], "errors.log"), 300) or "\u2705 \u0644\u0627 \u062a\u0648\u062c\u062f \u0623\u062e\u0637\u0627\u0621")


@app.route("/api/bot/install", methods=["POST"])
def bot_install():
    data = request.get_json(silent=True) or {}
    uname, _ = get_user_by_api_key(data.get("api_key"))
    folder = data.get("folder")
    if not uname:
        return jsonify(success=False), 401
    srv = db["servers"].get(folder)
    if not srv or srv.get("owner") != uname:
        return jsonify(success=False), 403
    threading.Thread(target=auto_install_deps,
                     args=(srv["path"], srv.get("type", "Python"), os.path.join(srv["path"], "out.log")),
                     daemon=True).start()
    return jsonify(success=True, message="\U0001f4e6 \u0628\u062f\u0623 \u0627\u0644\u062a\u062b\u0628\u064a\u062a")


@app.route("/api/bot/create_server", methods=["POST"])
def bot_create_server():
    data = request.get_json(silent=True) or {}
    uname, _ = get_user_by_api_key(data.get("api_key"))
    name = (data.get("name") or "").strip()
    if not uname:
        return jsonify(success=False, message="API Key \u063a\u064a\u0631 \u0635\u0627\u0644\u062d"), 401
    if not name:
        return jsonify(success=False, message="\u0627\u0644\u0631\u062c\u0627\u0621 \u0625\u062f\u062e\u0627\u0644 \u0627\u0633\u0645")
    folder, msg = _create_server(uname, name, data.get("server_type", "Python"))
    if not folder:
        return jsonify(success=False, message=msg)
    return jsonify(success=True, message=f"\u2705 \u062a\u0645 \u0625\u0646\u0634\u0627\u0621 {name}", folder=folder)


@app.route("/api/bot/pending")
def bot_pending():
    if not admin_access():
        return jsonify(success=False), 403
    return jsonify(success=True, requests=[{"username": u, "created_at": d.get("created_at")}
                   for u, d in db["users"].items() if d.get("status") == "pending"])


@app.route("/health")
def health():
    return jsonify(status="ok", psutil=HAS_PSUTIL)


# Pro extensions (activity, audit, 2FA, templates, env, backup, AI helpers, cron, uptime)
try:
    import app_pro  # noqa: F401
except Exception as _e:
    print("⚠️ app_pro load failed:", _e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
