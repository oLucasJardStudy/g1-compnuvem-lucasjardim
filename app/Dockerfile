FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# dependências primeiro: esta camada só é refeita se o requirements.txt mudar
COPY requirements.txt .
RUN pip install -r requirements.txt

# usuário sem privilégios e diretório de dados com a dona correta
RUN useradd --create-home --uid 1000 appuser \
 && mkdir /data \
 && chown appuser:appuser /data

COPY app.py .

USER appuser
EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/messages', timeout=2)" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "app:app"]
