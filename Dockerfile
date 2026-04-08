FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# يمكنك تغيير runner.py إلى min.py إذا أردت تشغيل البوت مباشرة بدون مدير التبديل
CMD ["python", "runner.py"]