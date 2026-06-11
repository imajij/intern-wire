FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/
COPY config.json .

# data lives on a mounted volume so listings survive redeploys
# (HOME=/tmp: hosts like HF Spaces run the container as a non-root user with
# no writable home, and scraper libs want somewhere to drop their caches)
ENV DB_PATH=/data/internships.db \
    PICKS_PATH=/data/picks.json \
    SCRAPE_INTERVAL_HOURS=8 \
    PORT=8000 \
    HOME=/tmp

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.server:app --host 0.0.0.0 --port ${PORT}"]
