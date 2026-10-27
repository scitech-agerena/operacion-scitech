FROM python:3.12-slim
WORKDIR /app
COPY mesas ./mesas
COPY config ./config
COPY ejecutar_mesa.py programador.py ./
RUN useradd --system --no-create-home app && mkdir -p /publicado /estado && chown app /publicado /estado
USER app
ENV PYTHONUNBUFFERED=1 PUBLICADO_DIR=/publicado ESTADO_DIR=/estado
CMD ["python3", "programador.py"]
