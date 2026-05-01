FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    python-telegram-bot==20.7 \
    flask \
    requests

COPY bot.py .

EXPOSE 7860

CMD ["python", "bot.py"]
