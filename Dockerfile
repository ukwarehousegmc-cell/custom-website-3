FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --retries 5 --timeout 60 -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --timeout 300 --workers 2 --log-level debug app:app"]
