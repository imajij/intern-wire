FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/
COPY config.json .

# data lives on a mounted volume so listings survive redeploys
ENV DB_PATH=/data/internships.db \
    SCRAPE_INTERVAL_HOURS=8 \
    PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.server:app --host 0.0.0.0 --port ${PORT}"]
