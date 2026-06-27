# -*- coding: utf-8 -*-
"""
𝑩𝑨𝑻𝑴𝑨𝑵 𝑫𝒆𝒗𓃠 - بوت التحكم (اختياري)
يعمل بالـ polling — يتواصل مع البانل عبر API Key.
شغّله منفصل: python telegram_bot.py
المتغيرات المطلوبة: BOT_TOKEN ، API_BASE_URL
"""
import os
import telebot
import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:5000").rstrip("/")

if not BOT_TOKEN:
    raise SystemExit("\u26a0\ufe0f \u062d\u0637 BOT_TOKEN \u0641\u064a \u0627\u0644\u0645\u062a\u063a\u064a\u0631\u0627\u062a")

bot = telebot.TeleBot(BOT_TOKEN)
USER_KEYS = {}  # chat_id -> api_key (ف\u064a \u0627\u0644\u0630\u0627\u0643\u0631\u0629)


def api_get(path, key, **params):
    params["api_key"] = key
    try:
        return requests.get(f"{API_BASE_URL}{path}", params=params, timeout=15).json()
    except Exception as e:
        return {"success": False, "message": str(e)}


def api_post(path, payload):
    try:
        return requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=20).json()
    except Exception as e:
        return {"success": False, "message": str(e)}


@bot.message_handler(commands=["start"])
def cmd_start(m):
    bot.reply_to(m, (
        "\U0001f44b \u0623\u0647\u0644\u0627\u064b \u0628\u0643 \u0641\u064a *𝑩𝑨𝑻𝑴𝑨𝑵 𝑫𝒆𝒗𓃠*\n\n"
        "\U0001f511 \u0627\u0631\u0628\u0637 \u062d\u0633\u0627\u0628\u0643:\n`/login <API_KEY>`\n\n"
        "\U0001f4cb \u0627\u0644\u0623\u0648\u0627\u0645\u0631:\n"
        "/servers - \u0633\u064a\u0631\u0641\u0631\u0627\u062a\u064a\n"
        "/new <name> - \u0633\u064a\u0631\u0641\u0631 \u062c\u062f\u064a\u062f\n"
        "/start_s <folder> - \u062a\u0634\u063a\u064a\u0644\n"
        "/stop_s <folder> - \u0625\u064a\u0642\u0627\u0641\n"
        "/restart <folder> - \u0625\u0639\u0627\u062f\u0629\n"
        "/logs <folder> - \u0627\u0644\u0643\u0648\u0646\u0633\u0648\u0644\n"
    ), parse_mode="Markdown")


@bot.message_handler(commands=["login"])
def cmd_login(m):
    parts = m.text.split()
    if len(parts) < 2:
        bot.reply_to(m, "\u2757 \u0627\u0644\u0635\u064a\u063a\u0629: /login <API_KEY>")
        return
    key = parts[1].strip()
    res = api_post("/api/bot/verify", {"api_key": key})
    if res.get("success"):
        USER_KEYS[m.chat.id] = key
        bot.reply_to(m, f"\u2705 \u062a\u0645 \u0631\u0628\u0637 \u062d\u0633\u0627\u0628 *{res.get('username')}*", parse_mode="Markdown")
    else:
        bot.reply_to(m, "\u274c API Key \u063a\u064a\u0631 \u0635\u0627\u0644\u062d")


def _require(m):
    key = USER_KEYS.get(m.chat.id)
    if not key:
        bot.reply_to(m, "\U0001f512 \u0627\u0631\u0628\u0637 \u062d\u0633\u0627\u0628\u0643 \u0623\u0648\u0644\u0627\u064b: /login <API_KEY>")
    return key


@bot.message_handler(commands=["servers"])
def cmd_servers(m):
    key = _require(m)
    if not key:
        return
    res = api_get("/api/bot/servers", key)
    servers = res.get("servers", [])
    if not servers:
        bot.reply_to(m, "\U0001f4ed \u0644\u0627 \u062a\u0648\u062c\u062f \u0633\u064a\u0631\u0641\u0631\u0627\u062a")
        return
    lines = []
    for s in servers:
        ic = "\U0001f7e2" if s.get("status") == "Running" else "\U0001f534"
        lines.append(f"{ic} *{s['title']}*\n   `{s['folder']}`\n   \U0001f50c {s.get('port')} | {s.get('type')}")
    bot.reply_to(m, "\n\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["new"])
def cmd_new(m):
    key = _require(m)
    if not key:
        return
    name = m.text.replace("/new", "", 1).strip()
    if not name:
        bot.reply_to(m, "\u2757 \u0627\u0644\u0635\u064a\u063a\u0629: /new <name>")
        return
    res = api_post("/api/bot/create_server", {"api_key": key, "name": name, "server_type": "Python"})
    bot.reply_to(m, res.get("message", "\u2705"))


def _action(m, action):
    key = _require(m)
    if not key:
        return
    parts = m.text.split()
    if len(parts) < 2:
        bot.reply_to(m, "\u2757 \u062d\u062f\u062f folder \u0627\u0644\u0633\u064a\u0631\u0641\u0631")
        return
    res = api_post("/api/bot/server/action", {"api_key": key, "folder": parts[1], "action": action})
    bot.reply_to(m, res.get("message", "\u2705"))


@bot.message_handler(commands=["start_s"])
def cmd_start_s(m):
    _action(m, "start")


@bot.message_handler(commands=["stop_s"])
def cmd_stop_s(m):
    _action(m, "stop")


@bot.message_handler(commands=["restart"])
def cmd_restart(m):
    _action(m, "restart")


@bot.message_handler(commands=["logs"])
def cmd_logs(m):
    key = _require(m)
    if not key:
        return
    parts = m.text.split()
    if len(parts) < 2:
        bot.reply_to(m, "\u2757 \u062d\u062f\u062f folder \u0627\u0644\u0633\u064a\u0631\u0641\u0631")
        return
    res = api_get("/api/bot/console", key, folder=parts[1])
    logs = (res.get("logs") or "\u0644\u0627 \u062a\u0648\u062c\u062f")[-3500:]
    bot.reply_to(m, f"```\n{logs}\n```", parse_mode="Markdown")


if __name__ == "__main__":
    print("\U0001f916 BATMAN Dev bot running...")
    bot.infinity_polling(skip_pending=True)
