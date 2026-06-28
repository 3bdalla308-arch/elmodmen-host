# -*- coding: utf-8 -*-
"""
BATMAN Dev — Pro Features Extension
يضيف للنظام الأساسي:
- Activity Feed + Audit Log
- Usage tracking + 80% warnings
- Trial 7 days + Coupons + Invoices
- Server templates + Env vars editor + Backup/Restore
- 2FA TOTP + Rate limiting + Session list
- Cron scheduler + Bot uptime
- Analytics for admin
- AI helpers (debug/generate/optimize)
يستورد من app.py: app, db, save_db, _lock, _now, login_required,
                 admin_access, is_admin, owned_server, safe_name,
                 user_servers_dir, groq_chat, USERS_DIR, BASE_DIR, DATA_DIR,
                 generate_api_key
"""
import os, io, json, time, base64, hmac, hashlib, struct, secrets, zipfile, shutil, threading
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict, deque
from flask import request, jsonify, send_file, session, Response

from app import (
    app, db, save_db, _lock, _now, login_required, admin_access,
    is_admin, owned_server, safe_name, user_servers_dir,
    groq_chat, USERS_DIR, BASE_DIR, DATA_DIR, generate_api_key,
)

# ---------------------------------------------------------------
# تهيئة الحقول الجديدة في قاعدة البيانات
# ---------------------------------------------------------------
def _ensure_schema():
    with _lock:
        db.setdefault("activity", [])         # سجل نشاط المستخدم
        db.setdefault("audit", [])             # سجل تدقيق الأدمن
        db.setdefault("coupons", {})           # أكواد خصم
        db.setdefault("sessions", [])          # جلسات الدخول
        db.setdefault("uptime", {})            # تتبع uptime البوتات
        db.setdefault("cron", [])              # المهام المجدولة
        db.setdefault("twofa", {})             # 2FA secrets
        # إضافة حقول لكل مستخدم
        for uname, u in db["users"].items():
            u.setdefault("trial_used", False)
            u.setdefault("trial_until", None)
            u.setdefault("plan_until", None)
            u.setdefault("theme", "dark")
            u.setdefault("onboarding_done", False)
        save_db(db)
_ensure_schema()


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------
ACTIVITY_LIMIT = 500
AUDIT_LIMIT = 1000
SESSION_LIMIT = 100

def log_activity(username, kind, message, icon=""):
    if not username:
        return
    item = {
        "id": secrets.token_hex(6),
        "user": username,
        "kind": kind,
        "message": message,
        "icon": icon or _kind_icon(kind),
        "at": _now(),
        "ts": int(time.time()),
    }
    with _lock:
        db["activity"].insert(0, item)
        db["activity"] = db["activity"][:ACTIVITY_LIMIT]
        save_db(db)

def log_audit(actor, action, target="", meta=None):
    item = {
        "id": secrets.token_hex(6),
        "actor": actor or "system",
        "action": action,
        "target": target,
        "meta": meta or {},
        "at": _now(),
        "ts": int(time.time()),
        "ip": (request.remote_addr if request else "") or "",
    }
    with _lock:
        db["audit"].insert(0, item)
        db["audit"] = db["audit"][:AUDIT_LIMIT]
        save_db(db)

def _kind_icon(kind):
    return {
        "server_create": "fa-plus",
        "server_start": "fa-play",
        "server_stop": "fa-stop",
        "server_delete": "fa-trash",
        "server_restart": "fa-rotate",
        "file_save": "fa-floppy-disk",
        "file_upload": "fa-upload",
        "login": "fa-arrow-right-to-bracket",
        "logout": "fa-arrow-right-from-bracket",
        "payment": "fa-credit-card",
        "plan_change": "fa-gem",
        "password_change": "fa-key",
        "ai": "fa-wand-magic-sparkles",
        "trial": "fa-gift",
        "coupon": "fa-ticket",
        "2fa": "fa-shield-halved",
        "backup": "fa-cloud-arrow-down",
        "restore": "fa-cloud-arrow-up",
    }.get(kind, "fa-circle-info")

def cur_user():
    return session.get("username")


# ---------------------------------------------------------------
# Rate limiting (in-memory)
# ---------------------------------------------------------------
_rl = defaultdict(lambda: deque())
def rate_limit(key_fn, max_calls=30, window=60):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            key = key_fn() or request.remote_addr or "x"
            now = time.time()
            dq = _rl[key]
            while dq and dq[0] < now - window:
                dq.popleft()
            if len(dq) >= max_calls:
                return jsonify(success=False, message="⏳ محاولات كتيرة، استنى شوية"), 429
            dq.append(now)
            return f(*a, **k)
        return w
    return deco


# ---------------------------------------------------------------
# Sessions tracking
# ---------------------------------------------------------------
def track_login(username):
    sid = session.get("sid") or secrets.token_hex(8)
    session["sid"] = sid
    ua = request.headers.get("User-Agent", "")[:200]
    ip = request.remote_addr or ""
    with _lock:
        # احذف القديمة لنفس الـ sid
        db["sessions"] = [s for s in db["sessions"] if s.get("sid") != sid]
        db["sessions"].insert(0, {
            "sid": sid, "user": username, "ua": ua, "ip": ip,
            "at": _now(), "ts": int(time.time()),
        })
        db["sessions"] = db["sessions"][:SESSION_LIMIT]
        save_db(db)

@app.route("/api/sessions")
@login_required
def list_sessions():
    u = cur_user()
    mine = [s for s in db.get("sessions", []) if s.get("user") == u]
    current = session.get("sid")
    for s in mine:
        s["current"] = (s.get("sid") == current)
    return jsonify(success=True, sessions=mine)

@app.route("/api/sessions/revoke", methods=["POST"])
@login_required
def revoke_session():
    sid = (request.get_json(silent=True) or {}).get("sid")
    u = cur_user()
    with _lock:
        db["sessions"] = [s for s in db["sessions"] if not (s.get("user") == u and s.get("sid") == sid)]
        save_db(db)
    if sid == session.get("sid"):
        session.clear()
    return jsonify(success=True, message="تم إنهاء الجلسة")


# ---------------------------------------------------------------
# Activity feed
# ---------------------------------------------------------------
@app.route("/api/activity")
@login_required
def api_activity():
    u = cur_user()
    mine = [a for a in db.get("activity", []) if a.get("user") == u][:80]
    return jsonify(success=True, activity=mine)

@app.route("/api/activity/clear", methods=["POST"])
@login_required
def api_activity_clear():
    u = cur_user()
    with _lock:
        db["activity"] = [a for a in db["activity"] if a.get("user") != u]
        save_db(db)
    return jsonify(success=True, message="اتمسحت")


# ---------------------------------------------------------------
# Admin: Audit log + Analytics
# ---------------------------------------------------------------
@app.route("/api/admin/audit")
def api_audit():
    if not admin_access():
        return jsonify(success=False), 403
    return jsonify(success=True, audit=db.get("audit", [])[:200])

@app.route("/api/admin/analytics")
def api_analytics():
    if not admin_access():
        return jsonify(success=False), 403
    users = db.get("users", {})
    payments = db.get("payments", [])
    servers = db.get("servers", {})
    # توزيع الخطط
    plan_dist = defaultdict(int)
    for u in users.values():
        plan_dist[u.get("plan", "free")] += 1
    # إيرادات شهرية (آخر 6 شهور)
    revenue = defaultdict(float)
    now = datetime.now()
    for p in payments:
        if p.get("status") != "approved":
            continue
        try:
            d = datetime.strptime(p.get("at", "")[:7], "%Y-%m")
            key = d.strftime("%Y-%m")
            revenue[key] += float(p.get("amount", 0))
        except Exception:
            pass
    months = []
    for i in range(5, -1, -1):
        d = (now.replace(day=15) - timedelta(days=30 * i))
        k = d.strftime("%Y-%m")
        months.append({"month": k, "revenue": revenue.get(k, 0)})
    # مستخدمين جدد آخر 7 أيام
    new_users = defaultdict(int)
    for u in users.values():
        try:
            d = u.get("created_at", "")[:10]
            if d:
                new_users[d] += 1
        except Exception:
            pass
    days = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        days.append({"day": d, "count": new_users.get(d, 0)})
    # totals
    total_revenue = sum(float(p.get("amount", 0)) for p in payments if p.get("status") == "approved")
    running = sum(1 for s in servers.values() if s.get("status") == "running")
    return jsonify(
        success=True,
        totals={
            "users": len(users),
            "servers": len(servers),
            "running": running,
            "revenue": total_revenue,
            "pending_payments": sum(1 for p in payments if p.get("status") == "pending"),
        },
        plan_distribution=dict(plan_dist),
        revenue_months=months,
        new_users_days=days,
    )


# ---------------------------------------------------------------
# Usage tracking (current usage vs plan limits)
# ---------------------------------------------------------------
def _dir_size_mb(path):
    total = 0
    if not os.path.exists(path):
        return 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return round(total / (1024 * 1024), 2)

@app.route("/api/usage")
@login_required
def api_usage():
    u = cur_user()
    user = db["users"].get(u, {})
    plan = db["plans"].get(user.get("plan", "free"), {})
    my_servers = [s for s in db["servers"].values() if s.get("owner") == u]
    used_storage = _dir_size_mb(user_servers_dir(u))
    used_servers = len(my_servers)
    max_servers = user.get("max_servers") or plan.get("max_servers", 1)
    max_storage = user.get("storage_limit") or plan.get("storage", 100)
    warn_storage = max_storage > 0 and used_storage / max_storage >= 0.8
    warn_servers = max_servers > 0 and used_servers / max_servers >= 0.8
    return jsonify(
        success=True,
        servers={"used": used_servers, "max": max_servers, "pct": round(100 * used_servers / max(1, max_servers))},
        storage={"used": used_storage, "max": max_storage, "pct": round(100 * used_storage / max(1, max_storage))},
        warning=warn_storage or warn_servers,
        plan_until=user.get("plan_until"),
        trial_until=user.get("trial_until"),
        trial_used=user.get("trial_used", False),
    )


# ---------------------------------------------------------------
# Trial 7 days
# ---------------------------------------------------------------
@app.route("/api/user/start-trial", methods=["POST"])
@login_required
def start_trial():
    u = cur_user()
    user = db["users"].get(u)
    if not user:
        return jsonify(success=False, message="غير موجود"), 404
    if user.get("trial_used"):
        return jsonify(success=False, message="الفترة التجريبية اتستخدمت قبل كده")
    plan_id = (request.get_json(silent=True) or {}).get("plan") or "4gb"
    plan = db["plans"].get(plan_id)
    if not plan:
        return jsonify(success=False, message="خطة غير معروفة")
    until = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    with _lock:
        user["trial_used"] = True
        user["trial_until"] = until
        user["plan"] = plan_id
        user["max_servers"] = plan.get("max_servers", 1)
        user["storage_limit"] = plan.get("storage", 100)
        save_db(db)
    log_activity(u, "trial", f"تم تفعيل التجريبي على {plan.get('name', plan_id)} لمدة 7 أيام")
    return jsonify(success=True, message="🎁 تم تفعيل التجريبي 7 أيام", until=until)


# ---------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------
@app.route("/api/admin/coupons")
def list_coupons():
    if not admin_access():
        return jsonify(success=False), 403
    return jsonify(success=True, coupons=db.get("coupons", {}))

@app.route("/api/admin/coupons/add", methods=["POST"])
def add_coupon():
    if not admin_access():
        return jsonify(success=False), 403
    d = request.get_json(silent=True) or {}
    code = (d.get("code") or "").strip().upper()
    if not code:
        return jsonify(success=False, message="كود مطلوب")
    with _lock:
        db["coupons"][code] = {
            "discount": int(d.get("discount", 0)),    # نسبة %
            "plan": d.get("plan"),                    # خطة محددة (اختياري)
            "max_uses": int(d.get("max_uses", 10)),
            "uses": 0,
            "created_at": _now(),
            "active": True,
        }
        save_db(db)
    log_audit(cur_user(), "coupon_add", code, {"discount": d.get("discount")})
    return jsonify(success=True, message="اتضاف")

@app.route("/api/admin/coupons/delete", methods=["POST"])
def del_coupon():
    if not admin_access():
        return jsonify(success=False), 403
    code = ((request.get_json(silent=True) or {}).get("code") or "").upper()
    with _lock:
        if code in db["coupons"]:
            del db["coupons"][code]
            save_db(db)
    log_audit(cur_user(), "coupon_delete", code)
    return jsonify(success=True, message="اتمسح")

@app.route("/api/user/redeem-coupon", methods=["POST"])
@login_required
def redeem_coupon():
    u = cur_user()
    code = ((request.get_json(silent=True) or {}).get("code") or "").strip().upper()
    c = db["coupons"].get(code)
    if not c or not c.get("active") or c.get("uses", 0) >= c.get("max_uses", 0):
        return jsonify(success=False, message="كود غير صالح")
    discount = int(c.get("discount", 0))
    plan = c.get("plan")
    with _lock:
        c["uses"] = c.get("uses", 0) + 1
        save_db(db)
    log_activity(u, "coupon", f"تم استخدام كوبون {code} ({discount}%)")
    return jsonify(success=True, message=f"✅ تم تطبيق خصم {discount}%", discount=discount, plan=plan)


# ---------------------------------------------------------------
# Server templates (boilerplates)
# ---------------------------------------------------------------
SERVER_TEMPLATES = {
    "echo_bot": {
        "name": "بوت Echo بسيط",
        "desc": "بوت تيليجرام يرد على الرسائل بنفس النص",
        "type": "Python",
        "icon": "fa-comment-dots",
        "files": {
            "main.py": (
                "import os, telebot\n"
                "BOT_TOKEN = os.getenv('BOT_TOKEN', '')\n"
                "bot = telebot.TeleBot(BOT_TOKEN)\n\n"
                "@bot.message_handler(commands=['start'])\n"
                "def start(m):\n    bot.reply_to(m, '👋 أهلاً! بوت Echo شغال.')\n\n"
                "@bot.message_handler(func=lambda m: True)\n"
                "def echo(m):\n    bot.reply_to(m, m.text)\n\n"
                "if __name__ == '__main__':\n    print('Bot starting...')\n    bot.infinity_polling()\n"
            ),
            "requirements.txt": "pyTelegramBotAPI==4.21.0\n",
            ".env.example": "BOT_TOKEN=ضع_التوكن_هنا\n",
        },
    },
    "ai_bot": {
        "name": "بوت AI (Groq)",
        "desc": "بوت ذكي يرد بـ Groq AI",
        "type": "Python",
        "icon": "fa-wand-magic-sparkles",
        "files": {
            "main.py": (
                "import os, requests, telebot\n"
                "BOT_TOKEN = os.getenv('BOT_TOKEN', '')\n"
                "GROQ_KEY = os.getenv('GROQ_KEY', '')\n"
                "bot = telebot.TeleBot(BOT_TOKEN)\n\n"
                "def ask_ai(q):\n"
                "    r = requests.post('https://api.groq.com/openai/v1/chat/completions',\n"
                "        headers={'Authorization': f'Bearer {GROQ_KEY}'},\n"
                "        json={'model':'llama-3.3-70b-versatile','messages':[{'role':'user','content':q}]},\n"
                "        timeout=30)\n"
                "    return r.json()['choices'][0]['message']['content']\n\n"
                "@bot.message_handler(func=lambda m: True)\n"
                "def chat(m):\n"
                "    try:\n        bot.reply_to(m, ask_ai(m.text))\n"
                "    except Exception as e:\n        bot.reply_to(m, f'خطأ: {e}')\n\n"
                "if __name__ == '__main__':\n    bot.infinity_polling()\n"
            ),
            "requirements.txt": "pyTelegramBotAPI==4.21.0\nrequests==2.32.3\n",
            ".env.example": "BOT_TOKEN=ضع_التوكن\nGROQ_KEY=ضع_المفتاح\n",
        },
    },
    "flask_api": {
        "name": "Flask API",
        "desc": "API بسيط بـ Flask",
        "type": "Python",
        "icon": "fa-server",
        "files": {
            "main.py": (
                "from flask import Flask, jsonify\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/')\n"
                "def home():\n    return jsonify(message='Hello from BATMAN Dev', status='ok')\n\n"
                "@app.route('/health')\n"
                "def health():\n    return 'OK'\n\n"
                "if __name__ == '__main__':\n    import os\n    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))\n"
            ),
            "requirements.txt": "Flask==3.0.3\n",
        },
    },
    "node_express": {
        "name": "Node Express",
        "desc": "سيرفر Node.js بـ Express",
        "type": "Node.js",
        "icon": "fa-node-js",
        "files": {
            "index.js": (
                "const express = require('express');\n"
                "const app = express();\n"
                "app.get('/', (req,res) => res.json({msg:'Hello from BATMAN Dev'}));\n"
                "app.get('/health', (req,res) => res.send('OK'));\n"
                "app.listen(process.env.PORT || 3000, () => console.log('up'));\n"
            ),
            "package.json": '{\n  "name": "my-bot",\n  "version": "1.0.0",\n  "main": "index.js",\n  "dependencies": {"express": "^4.19.2"}\n}\n',
        },
    },
    "discord_bot": {
        "name": "بوت Discord",
        "desc": "بوت Discord أساسي",
        "type": "Python",
        "icon": "fa-discord",
        "files": {
            "main.py": (
                "import os, discord\n"
                "intents = discord.Intents.default(); intents.message_content = True\n"
                "client = discord.Client(intents=intents)\n\n"
                "@client.event\n"
                "async def on_ready():\n    print(f'Logged in as {client.user}')\n\n"
                "@client.event\n"
                "async def on_message(m):\n"
                "    if m.author == client.user: return\n"
                "    if m.content.startswith('!ping'):\n        await m.channel.send('🏓 pong')\n\n"
                "client.run(os.getenv('DISCORD_TOKEN', ''))\n"
            ),
            "requirements.txt": "discord.py==2.4.0\n",
            ".env.example": "DISCORD_TOKEN=ضع_التوكن\n",
        },
    },
}

@app.route("/api/templates")
@login_required
def list_templates():
    return jsonify(success=True, templates=[
        {"id": k, "name": v["name"], "desc": v["desc"], "type": v["type"], "icon": v["icon"]}
        for k, v in SERVER_TEMPLATES.items()
    ])

@app.route("/api/templates/install", methods=["POST"])
@login_required
def install_template():
    d = request.get_json(silent=True) or {}
    tpl_id = d.get("template")
    name = (d.get("name") or "").strip()
    if tpl_id not in SERVER_TEMPLATES:
        return jsonify(success=False, message="قالب غير معروف")
    tpl = SERVER_TEMPLATES[tpl_id]
    # نستخدم منطق إنشاء السيرفر من app.py
    from app import _create_server
    folder, msg = _create_server(cur_user(), name or tpl["name"], tpl["type"])
    if not folder:
        return jsonify(success=False, message=msg)
    srv = db["servers"][folder]
    for fn, content in tpl["files"].items():
        try:
            fp = os.path.join(srv["path"], fn)
            os.makedirs(os.path.dirname(fp) or srv["path"], exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass
    log_activity(cur_user(), "server_create", f"تم إنشاء بوت من القالب: {tpl['name']}")
    return jsonify(success=True, message=f"✅ تم إنشاء {name or tpl['name']}", folder=folder)


# ---------------------------------------------------------------
# Env vars editor (.env per server)
# ---------------------------------------------------------------
@app.route("/api/server/env/<folder>")
@login_required
def get_env(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False), 404
    env_path = os.path.join(srv["path"], ".env")
    pairs = []
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    pairs.append({"key": k.strip(), "value": v.strip()})
        except Exception:
            pass
    return jsonify(success=True, env=pairs)

@app.route("/api/server/env/<folder>", methods=["POST"])
@login_required
def save_env(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False), 404
    d = request.get_json(silent=True) or {}
    pairs = d.get("env", [])
    env_path = os.path.join(srv["path"], ".env")
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            for p in pairs:
                k = (p.get("key") or "").strip()
                v = (p.get("value") or "").strip()
                if k:
                    f.write(f"{k}={v}\n")
        log_activity(cur_user(), "file_save", f"تم حفظ متغيرات البيئة لـ {srv.get('name', folder)}")
        return jsonify(success=True, message="💾 اتحفظ")
    except Exception as e:
        return jsonify(success=False, message=str(e))


# ---------------------------------------------------------------
# Backup / Restore
# ---------------------------------------------------------------
@app.route("/api/server/backup/<folder>")
@login_required
def backup_server(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False), 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(srv["path"]):
            for f in files:
                if f in ("out.log", "errors.log") or f.endswith(".pyc"):
                    continue
                fp = os.path.join(root, f)
                arc = os.path.relpath(fp, srv["path"])
                try:
                    z.write(fp, arc)
                except Exception:
                    pass
    buf.seek(0)
    log_activity(cur_user(), "backup", f"تم تحميل نسخة احتياطية من {srv.get('name', folder)}")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{srv.get('name', folder)}_backup.zip")

@app.route("/api/server/restore/<folder>", methods=["POST"])
@login_required
def restore_server(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False), 404
    f = request.files.get("file")
    if not f:
        return jsonify(success=False, message="ارفع ملف zip")
    try:
        buf = io.BytesIO(f.read())
        with zipfile.ZipFile(buf) as z:
            for member in z.namelist():
                if ".." in member or member.startswith("/"):
                    continue
                z.extract(member, srv["path"])
        log_activity(cur_user(), "restore", f"تم استرجاع نسخة احتياطية إلى {srv.get('name', folder)}")
        return jsonify(success=True, message="📦 اتم الاسترجاع")
    except Exception as e:
        return jsonify(success=False, message=str(e))

@app.route("/api/admin/db-backup")
def db_backup():
    if not admin_access():
        return jsonify(success=False), 403
    if not os.path.exists(os.path.join(DATA_DIR, "db.json")):
        return jsonify(success=False, message="لا توجد قاعدة بيانات")
    return send_file(os.path.join(DATA_DIR, "db.json"),
                     mimetype="application/json",
                     as_attachment=True,
                     download_name=f"db_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json")


# ---------------------------------------------------------------
# 2FA (TOTP بدون مكتبة pyotp — تنفيذ يدوي بـ HMAC-SHA1)
# ---------------------------------------------------------------
def _b32_decode(s):
    return base64.b32decode(s + "=" * ((8 - len(s) % 8) % 8))

def totp_now(secret, t=None, step=30, digits=6):
    t = int(t if t is not None else time.time())
    ctr = t // step
    key = _b32_decode(secret.upper().replace(" ", ""))
    msg = struct.pack(">Q", ctr)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)

def totp_verify(secret, code, step=30, window=1):
    code = (code or "").strip()
    t = int(time.time())
    for w in range(-window, window + 1):
        if totp_now(secret, t + w * step) == code:
            return True
    return False

def gen_b32(length=20):
    rnd = secrets.token_bytes(length)
    return base64.b32encode(rnd).decode().rstrip("=")

@app.route("/api/2fa/setup", methods=["POST"])
@login_required
def twofa_setup():
    u = cur_user()
    secret = gen_b32()
    with _lock:
        db["twofa"][u] = {"secret": secret, "enabled": False, "created_at": _now()}
        save_db(db)
    issuer = "BATMAN%20Dev"
    uri = f"otpauth://totp/{issuer}:{u}?secret={secret}&issuer={issuer}&digits=6&period=30"
    return jsonify(success=True, secret=secret, otpauth=uri)

@app.route("/api/2fa/verify", methods=["POST"])
@login_required
def twofa_verify():
    u = cur_user()
    code = ((request.get_json(silent=True) or {}).get("code") or "").strip()
    info = db["twofa"].get(u)
    if not info:
        return jsonify(success=False, message="فعّل 2FA أولاً")
    if not totp_verify(info["secret"], code):
        return jsonify(success=False, message="كود غلط")
    with _lock:
        info["enabled"] = True
        save_db(db)
    log_activity(u, "2fa", "تم تفعيل التحقق الثنائي")
    return jsonify(success=True, message="🛡️ التفعيل تم")

@app.route("/api/2fa/disable", methods=["POST"])
@login_required
def twofa_disable():
    u = cur_user()
    with _lock:
        if u in db["twofa"]:
            del db["twofa"][u]
            save_db(db)
    log_activity(u, "2fa", "تم إلغاء التحقق الثنائي")
    return jsonify(success=True, message="تم الإلغاء")

@app.route("/api/2fa/status")
@login_required
def twofa_status():
    u = cur_user()
    info = db["twofa"].get(u, {})
    return jsonify(success=True, enabled=info.get("enabled", False))


# ---------------------------------------------------------------
# AI helpers (debug / generate / optimize)
# ---------------------------------------------------------------
@app.route("/api/ai/debug", methods=["POST"])
@login_required
def ai_debug():
    d = request.get_json(silent=True) or {}
    err = (d.get("error") or "").strip()
    code = (d.get("code") or "").strip()[:3000]
    if not err:
        return jsonify(success=False, message="مفيش خطأ")
    msgs = [
        {"role": "system", "content": "أنت مساعد برمجة بالعربية. اشرح الخطأ في 3 سطور ثم اقترح الإصلاح في كود نظيف."},
        {"role": "user", "content": f"الخطأ:\n{err[:2500]}\n\nالكود:\n{code}"},
    ]
    ans = groq_chat(msgs, model="smart", max_tokens=900)
    log_activity(cur_user(), "ai", "تشخيص خطأ بالذكاء الاصطناعي")
    return jsonify(success=True, answer=ans)

@app.route("/api/ai/generate", methods=["POST"])
@login_required
def ai_generate():
    d = request.get_json(silent=True) or {}
    prompt = (d.get("prompt") or "").strip()
    lang = d.get("lang", "python")
    if not prompt:
        return jsonify(success=False, message="اكتب وصف للبوت")
    msgs = [
        {"role": "system", "content": f"أنت مولّد كود {lang}. أرجع كود كامل قابل للتشغيل فقط داخل ```{lang} ... ``` بدون شرح."},
        {"role": "user", "content": prompt},
    ]
    ans = groq_chat(msgs, model="smart", max_tokens=1500)
    log_activity(cur_user(), "ai", "توليد كود بالذكاء الاصطناعي")
    return jsonify(success=True, answer=ans)

@app.route("/api/ai/optimize", methods=["POST"])
@login_required
def ai_optimize():
    d = request.get_json(silent=True) or {}
    code = (d.get("code") or "").strip()[:5000]
    if not code:
        return jsonify(success=False, message="مفيش كود")
    msgs = [
        {"role": "system", "content": "أنت محسّن كود. اقترح تحسينات للأداء والقراءة في نقاط مرقمة، ثم أعد الكود المحسن."},
        {"role": "user", "content": code},
    ]
    ans = groq_chat(msgs, model="smart", max_tokens=1500)
    log_activity(cur_user(), "ai", "تحسين كود بالذكاء الاصطناعي")
    return jsonify(success=True, answer=ans)


# ---------------------------------------------------------------
# Cron scheduler (مهام مجدولة بسيطة)
# ---------------------------------------------------------------
@app.route("/api/cron/list")
@login_required
def cron_list():
    u = cur_user()
    mine = [c for c in db.get("cron", []) if c.get("owner") == u]
    return jsonify(success=True, jobs=mine)

@app.route("/api/cron/add", methods=["POST"])
@login_required
def cron_add():
    d = request.get_json(silent=True) or {}
    folder = d.get("folder")
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False, message="بوت غير موجود")
    action = d.get("action", "restart")
    every = max(60, int(d.get("every_seconds", 3600)))
    job = {
        "id": secrets.token_hex(6),
        "owner": cur_user(),
        "folder": folder,
        "server_name": srv.get("name", folder),
        "action": action,
        "every": every,
        "last_run": 0,
        "created_at": _now(),
    }
    with _lock:
        db["cron"].append(job)
        save_db(db)
    log_activity(cur_user(), "server_restart", f"تم جدولة {action} كل {every//60} دقيقة لـ {job['server_name']}")
    return jsonify(success=True, message="⏰ اتجدول", job=job)

@app.route("/api/cron/delete", methods=["POST"])
@login_required
def cron_del():
    jid = (request.get_json(silent=True) or {}).get("id")
    u = cur_user()
    with _lock:
        db["cron"] = [c for c in db["cron"] if not (c.get("id") == jid and c.get("owner") == u)]
        save_db(db)
    return jsonify(success=True, message="اتمسح")

def _cron_loop():
    while True:
        try:
            now = int(time.time())
            jobs = list(db.get("cron", []))
            for j in jobs:
                if now - j.get("last_run", 0) >= j.get("every", 3600):
                    folder = j["folder"]
                    srv = db["servers"].get(folder)
                    if srv:
                        try:
                            from app import start_server_process, stop_server_process, restart_server
                            act = j.get("action", "restart")
                            if act == "start":
                                start_server_process(folder)
                            elif act == "stop":
                                stop_server_process(folder)
                            else:
                                restart_server(folder)
                            log_activity(j["owner"], f"server_{act}", f"⏰ مجدولة: {act} على {srv.get('name', folder)}")
                        except Exception:
                            pass
                    with _lock:
                        j["last_run"] = now
                        save_db(db)
        except Exception:
            pass
        time.sleep(30)

threading.Thread(target=_cron_loop, daemon=True).start()


# ---------------------------------------------------------------
# Uptime tracking
# ---------------------------------------------------------------
def _uptime_loop():
    while True:
        try:
            now = int(time.time())
            for folder, srv in list(db.get("servers", {}).items()):
                bucket = db.setdefault("uptime", {}).setdefault(folder, {"up": 0, "total": 0, "last": now})
                bucket["total"] += 1
                if srv.get("status") == "running":
                    bucket["up"] += 1
                bucket["last"] = now
            save_db(db)
        except Exception:
            pass
        time.sleep(60)

threading.Thread(target=_uptime_loop, daemon=True).start()

@app.route("/api/server/uptime/<folder>")
@login_required
def get_uptime(folder):
    srv = owned_server(folder)
    if not srv:
        return jsonify(success=False), 404
    b = db.get("uptime", {}).get(folder, {})
    pct = round(100 * b.get("up", 0) / max(1, b.get("total", 0)), 2)
    return jsonify(success=True, uptime=pct, samples=b.get("total", 0))


# ---------------------------------------------------------------
# Preferences (theme/onboarding)
# ---------------------------------------------------------------
@app.route("/api/prefs", methods=["GET", "POST"])
@login_required
def prefs():
    u = cur_user()
    user = db["users"].get(u, {})
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        with _lock:
            if "theme" in d:
                user["theme"] = d["theme"]
            if "onboarding_done" in d:
                user["onboarding_done"] = bool(d["onboarding_done"])
            save_db(db)
    return jsonify(success=True,
                   theme=user.get("theme", "dark"),
                   onboarding_done=user.get("onboarding_done", False))


print("✅ BATMAN Dev Pro extensions loaded")
