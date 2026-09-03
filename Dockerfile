FROM python:3.11-slim

WORKDIR /app

# Copie le code de l'application (les données persistantes vivent dans /app/data,
# monté en volume — voir docker-compose.yml — donc jamais écrasées par une rebuild).
COPY server.py index.html ./

EXPOSE 3210

CMD ["python", "server.py"]
