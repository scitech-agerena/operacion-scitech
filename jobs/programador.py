#!/usr/bin/env python3
"""Programador de los tableros: ejecuta cada tablero activo cada 30 minutos en horario laboral.

Reglas (hora de Bogotá, UTC-5):
  - lunes a viernes, sin festivos (config/festivos.json),
  - entre las 6:00 y las 19:30,
  - una corrida cada INTERVALO_MIN minutos (por defecto 30); los tableros se ejecutan de a uno.

Variables: JOBS_ACTIVOS (lista separada por comas, por defecto interna_nueva), INTERVALO_MIN.
"""
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
BOGOTA = dt.timezone(dt.timedelta(hours=-5))
INICIO, FIN = dt.time(6, 0), dt.time(19, 30)


def cargar_festivos(ruta=AQUI / "config" / "festivos.json"):
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return {a: set(v) for a, v in datos.items() if not a.startswith("_")}


def es_dia_habil(fecha, festivos):
    return fecha.weekday() < 5 and fecha.isoformat() not in festivos.get(str(fecha.year), set())


def debe_correr(ahora, ultimo_intento, festivos, intervalo_min=30):
    """`ahora` y `ultimo_intento` en hora de Bogotá (datetime con zona). Función pura, con pruebas."""
    if not es_dia_habil(ahora.date(), festivos):
        return False
    if not (INICIO <= ahora.time() < FIN):
        return False
    return ultimo_intento is None or (ahora - ultimo_intento) >= dt.timedelta(minutes=intervalo_min)


def main():
    activos = [j.strip() for j in os.environ.get("JOBS_ACTIVOS", "interna_nueva").split(",") if j.strip()]
    intervalo = int(os.environ.get("INTERVALO_MIN", 30))
    festivos = cargar_festivos()
    ultimo = {j: None for j in activos}
    avisado = set()
    parar = []
    signal.signal(signal.SIGTERM, lambda *_: parar.append(1))
    signal.signal(signal.SIGINT, lambda *_: parar.append(1))
    print(json.dumps({"evento": "programador_iniciado", "tableros": activos, "cada_min": intervalo}), flush=True)

    while not parar:
        ahora = dt.datetime.now(BOGOTA)
        if str(ahora.year) not in festivos and ahora.year not in avisado:
            avisado.add(ahora.year)
            print(json.dumps({"evento": "aviso", "mensaje": f"config/festivos.json no tiene el año {ahora.year}; los festivos se tratan como días hábiles"}), flush=True)
        for job in activos:
            if parar:
                break
            if debe_correr(ahora, ultimo[job], festivos, intervalo):
                ultimo[job] = ahora
                subprocess.run([sys.executable, str(AQUI / "ejecutar_mesa.py"), job])
                ahora = dt.datetime.now(BOGOTA)
        time.sleep(20)


if __name__ == "__main__":
    main()
