# -*- coding: utf-8 -*-
# إعدادات gunicorn — يقرأ المنفذ من البيئة مباشرة (يحل مشكلة $PORT على Railway)
import os

bind = "0.0.0.0:" + os.environ.get("PORT", "5000")
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("WEB_THREADS", "8"))
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
