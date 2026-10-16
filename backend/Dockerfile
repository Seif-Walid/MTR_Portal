FROM python:3.13-slim

WORKDIR /app

# LibreOffice renders office files (.pptx/.docx/.xlsx) to PDF so the Courses
# viewer shows them inline. Only the headless Impress/Writer/Calc filters and a
# base font set — no recommends — to keep the image lean. It runs only at
# upload/backfill time, never on the serving path.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-impress libreoffice-writer libreoffice-calc \
        fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
