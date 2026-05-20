FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

RUN pip install \
    flask \
    requests \
    python-telegram-bot \
    yt-dlp

EXPOSE 10000

CMD ["python", "bot.py"]
