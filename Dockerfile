FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TZ=America/Sao_Paulo

WORKDIR /app

# Dependências primeiro (cache de camada).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código.
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/

EXPOSE 8000

# Servidor de produção (gunicorn). 1 worker para o lock de sync em memória ser único;
# threads para servir o dashboard durante um sync em background.
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "120", \
     "--bind", "0.0.0.0:8000", "--access-logfile", "-", "src.web:app"]
