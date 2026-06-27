#!/usr/bin/env bash
# =====================================================================
# 🔒 حماية الكود قبل الرفع
#   - الباك إند: تعمية بـ PyArmor
#   - الفرونت إند: تصغير/تعمية JS بـ terser
# الاستخدام:  bash scripts/build_protect.sh
# بعدها ارفع محتويات مجلد dist/ فقط.
# =====================================================================
set -e
cd "$(dirname "$0")/.."   # الانتقال لجذر المشروع

echo "==> [1/3] تعمية الباك إند بـ PyArmor ..."
pip install --quiet --upgrade pyarmor
rm -rf dist
pyarmor gen -O dist -r app.py telegram_bot.py
cp -r templates dist/templates
cp -r static dist/static 2>/dev/null || true
cp requirements.txt runtime.txt Procfile dist/ 2>/dev/null || true

echo "==> [2/3] تصغير/تعمية جافاسكربت الواجهة بـ terser ..."
if [ ! -d node_modules/terser ]; then npm i terser; fi
node scripts/minify_templates.js dist/templates

echo "==> [3/3] تم ✅"
echo "    • الكود المحمي في:  dist/"
echo "    • مفيش أي ملف .py مقروء جوه dist/"
