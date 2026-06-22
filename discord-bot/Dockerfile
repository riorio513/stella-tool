FROM python:3.12-slim

WORKDIR /app

# 依存だけ先に入れてレイヤーキャッシュを効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# data/ は永続ボリュームにマウントすると取り込み済みデータが消えない
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
