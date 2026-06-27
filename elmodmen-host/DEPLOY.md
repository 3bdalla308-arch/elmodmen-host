# 🚀 دليل الرفع على GitHub + Railway

## 1️⃣ رفع الكود على GitHub
```bash
cd elmodmen-host
git init
git add .
git commit -m "BATMAN Dev Hosting Panel"
git branch -M main
git remote add origin https://github.com/<اسمك>/<الريبو>.git
git push -u origin main
```
> ✅ خلّي الريبو **Private** لحماية الكود.

## 2️⃣ النشر على Railway
1. ادخل [railway.app](https://railway.app) ← **New Project** ← **Deploy from GitHub repo**.
2. اختار الريبو بتاعك. Railway هيكتشف الإعدادات تلقائيًا من `railway.json` و `Procfile`.
3. من **Settings ← Networking** اضغط **Generate Domain** عشان تاخد لينك.

### متغيرات البيئة (Variables) — مهمة
حطهم من تبويب **Variables** في Railway:

| المتغير | القيمة |
|---|---|
| `SECRET_KEY` | أي نص عشوائي طويل |
| `ADMIN_USER` | `admin` |
| `ADMIN_PASS` | `16102010` |
| `BOT_TOKEN` | توكن بوت تليجرام (اختياري) |
| `ADMIN_TELEGRAM_ID` | آيدي الأدمن على تليجرام (اختياري) |

> 🔒 لو ما حطيتش `ADMIN_USER`/`ADMIN_PASS` هيستخدم الافتراضي `admin` / `16102010`.

## 3️⃣ (اختياري) نشر بالكود المحمي
لو عايز الكود يترفع مُعمّى (Obfuscated):
- في Railway: **Settings ← Build ← Builder → Dockerfile** (هيستخدم `Dockerfile` اللي بيعمّي بـ PyArmor تلقائيًا).
- أو محليًا: `bash scripts/build_protect.sh` ثم ارفع محتويات `dist/`.

## 📝 ملاحظات
- `--workers 1` **إجباري** (عشان إدارة السيرفرات تشتغل صح).
- التخزين على Railway مؤقت — لو عايز ثبات دائم استخدم **Volume** من Railway ووجّه `DATA_DIR` ليه، أو **VPS** حقيقي.
- للتشغيل الفعلي للبوتات على مدار الساعة، **VPS** أفضل من الإستضافات المؤقتة.
