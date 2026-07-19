FROM python:3.11-slim

# ffmpeg لازم لدمج الفيديو والصوت (جودة 4K) - غير موجود بشكل افتراضي عند Render
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# مجلد المستخدمين (تحميلات + سجلات) - يتصفّر عند كل إعادة تشغيل على الخطة المجانية، وهذا طبيعي
RUN mkdir -p users templates static logs cache

EXPOSE 5001

# gunicorn مع gthread عشان يدعم الـ SSE (شريط التقدم) والتحميلات الطويلة بدون ما يتقطع الاتصال
CMD gunicorn run:app \
    --bind 0.0.0.0:${PORT:-5001} \
    --worker-class gthread \
    --workers 1 \
    --threads 8 \
    --timeout 900 \
    --graceful-timeout 30
