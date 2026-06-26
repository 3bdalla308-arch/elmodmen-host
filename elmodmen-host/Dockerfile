# 🔒 Dockerfile — يبني نسخة الباك إند مُعمّاة (Obfuscated) بـ PyArmor
# استخدمه على Railway (Deploy from Dockerfile) للحصول على كود محمي تلقائيًا.
FROM python:3.11-slim

WORKDIR /app

# تثبيت المكتبات + أداة الحماية
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pyarmor

# نسخ كل المشروع
COPY . .

# تعمية كود البايثون -> مجلد dist (مفيش أي سورس مقروء)
RUN pyarmor gen -O dist -r app.py telegram_bot.py \
 && cp -r templates dist/templates \
 && cp requirements.txt runtime.txt dist/ 2>/dev/null || true

WORKDIR /app/dist

ENV PORT=5000
EXPOSE 5000

# تشغيل النسخة المحمية
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120
