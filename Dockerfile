FROM python:3.14-slim

# Устанавливаем Node.js (нужен для node --check) и зависимости Playwright
RUN apt-get update && apt-get install -y nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "main.py"]