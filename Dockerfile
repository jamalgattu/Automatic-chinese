FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install --upgrade pip

RUN pip install \
    flask \
    requests \
    python-telegram-bot \
    yt-dlp \
    gunicorn

EXPOSE 10000

CMD ["python", "bot.py"]
