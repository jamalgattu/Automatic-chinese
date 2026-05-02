FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    python-telegram-bot==20.7 \
    flask \
    requests \
    gunicorn

COPY bot.py .

EXPOSE 7860

CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", "bot:flask_app"]
