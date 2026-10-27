#!/usr/bin/env python3
"""Ejecuta un tablero de mesa de servicio: consulta Jira, genera el HTML y lo publica de forma atómica.

Uso:  python3 ejecutar_mesa.py <perfil>        (perfiles: interna_nueva, salud360, vigentes)

Usa el generador de siempre (mesas/generar_tablero.py) sin modificarlo. Este archivo solo:
  - fija el sitio y las credenciales de Jira de cada perfil (solo lectura),
  - reintenta ante fallos de red o límites de la API,
  - compara con la corrida anterior antes de publicar (cuadre),
  - escribe en un archivo temporal y lo renombra, de modo que quien abra el tablero siempre ve una versión completa,
  - conserva la última versión buena si algo falla.

Variables de entorno:
  JIRA_SCITECH_URL / _EMAIL / _TOKEN     y     JIRA_SALUD360_URL / _EMAIL / _TOKEN
  PUBLICADO_DIR   carpeta que sirve Caddy (por defecto ./salida/publicado)
  ESTADO_DIR      carpeta del estado de cada corrida (por defecto ./salida/estado)
  REINTENTOS (3), ESPERA_S (45), TIMEOUT_S (1500)
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent

# dir      = carpeta publicada (coincide con el identificador del tablero en access.json)
# sitio    = prefijo de las variables JIRA_<SITIO>_*
# max_baja = caída máxima aceptada del número de solicitudes respecto a la corrida anterior
PERFILES = {
    "interna_nueva": {"dir": "mesas-interna", "sitio": "SCITECH", "max_baja": 0.05},
    "salud360": {"dir": "mesas-salud360", "sitio": "SALUD360", "max_baja": 0.15},
    "vigentes": {"dir": "mesas-clientes", "sitio": "SCITECH", "max_baja": 0.10},
}


def log(**kv):
    kv = {"t": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **kv}
    print(json.dumps(kv, ensure_ascii=False), flush=True)


def entorno_generador(perfil, env):
    """Variables que espera generar_tablero.py (nunca se imprimen)."""
    cfg = PERFILES[perfil]
    pre = f"JIRA_{cfg['sitio']}_"
    faltan = [k for k in (pre + "URL", pre + "EMAIL", pre + "TOKEN") if not env.get(k)]
    if faltan:
        raise SystemExit("Faltan variables de entorno: " + ", ".join(faltan))
    e = dict(env)
    e["PERFIL"] = perfil
    # El generador consulta JIRA_SITE; para Salud 360 debe ser el sitio de Salud 360, no el de Scitech.
    e["JIRA_SITE"] = env[pre + "URL"].rstrip("/")
    e["JIRA_EMAIL"] = env[pre + "EMAIL"]
    e["JIRA_API_TOKEN"] = env[pre + "TOKEN"]
    if perfil == "salud360":
        e["JIRA_SITE_S360"] = e["JIRA_SITE"]
        e["INCLUIR_TEXTOS"] = "0"  # los resúmenes de Salud 360 pueden contener datos de salud: nunca se publican
    e.pop("MODO_PUBLICO", None)
    return e


def contar_filas(html):
    """Número de solicitudes que incrusta el HTML (para el cuadre)."""
    # La plantilla incrusta: const PF=...,RAW=<filas>,GEN=new Date("...")
    m = re.search(r",RAW=(\[.*?\]),GEN=new Date\(", html, re.S)
    if not m:
        return None
    try:
        return len(json.loads(m.group(1).replace("<\\/", "</")))
    except ValueError:
        return None


def ejecutar(perfil, env=None):
    env = os.environ if env is None else env
    cfg = PERFILES[perfil]
    publicado = Path(env.get("PUBLICADO_DIR", AQUI / "salida" / "publicado")) / cfg["dir"]
    estado_dir = Path(env.get("ESTADO_DIR", AQUI / "salida" / "estado"))
    publicado.mkdir(parents=True, exist_ok=True)
    estado_dir.mkdir(parents=True, exist_ok=True)
    estado_file = estado_dir / f"{perfil}.json"
    estado = json.loads(estado_file.read_text()) if estado_file.exists() else {}

    e = entorno_generador(perfil, env)
    reintentos, espera = int(env.get("REINTENTOS", 3)), float(env.get("ESPERA_S", 45))
    destino = publicado / "index.html"
    tmp = publicado / f".index.html.tmp-{os.getpid()}"
    inicio = time.time()
    ultimo_error = None

    for intento in range(1, reintentos + 1):
        try:
            r = subprocess.run(
                [sys.executable, str(AQUI / "mesas" / "generar_tablero.py"), "--salida", str(tmp)],
                env=e, capture_output=True, text=True, timeout=float(env.get("TIMEOUT_S", 1500)),
            )
            if r.returncode == 0 and tmp.exists():
                break
            ultimo_error = (r.stderr or "").strip().splitlines()[-1:] or ["el generador terminó con error"]
            ultimo_error = ultimo_error[0][:300]
        except subprocess.TimeoutExpired:
            ultimo_error = "tiempo de espera agotado"
        tmp.unlink(missing_ok=True)
        log(perfil=perfil, evento="reintento", intento=intento, error=ultimo_error)
        if intento < reintentos:
            time.sleep(espera * intento)
    else:
        estado.update({"ultimo_error": ultimo_error, "ultimo_error_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
        estado_file.write_text(json.dumps(estado, ensure_ascii=False, indent=1))
        log(perfil=perfil, evento="fallo", error=ultimo_error, publicado="se conserva la versión anterior")
        return 1

    html = tmp.read_text(encoding="utf-8")
    n = contar_filas(html)
    previo = estado.get("solicitudes")
    problema = None
    if not n:
        problema = "el tablero no trae solicitudes"
    elif previo and n < previo * (1 - cfg["max_baja"]):
        problema = f"las solicitudes bajaron de {previo} a {n} (más de {int(cfg['max_baja'] * 100)} %)"
    if problema:
        tmp.unlink(missing_ok=True)
        estado.update({"ultimo_error": "cuadre: " + problema, "ultimo_error_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
        estado_file.write_text(json.dumps(estado, ensure_ascii=False, indent=1))
        log(perfil=perfil, evento="cuadre_fallido", error=problema, publicado="se conserva la versión anterior")
        return 2

    os.replace(tmp, destino)  # publicación atómica
    estado = {
        "perfil": perfil,
        "ultima_ok_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "solicitudes": n,
        "duracion_s": round(time.time() - inicio, 1),
    }
    estado_file.write_text(json.dumps(estado, ensure_ascii=False, indent=1))
    log(perfil=perfil, evento="publicado", solicitudes=n, duracion_s=estado["duracion_s"])
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in PERFILES:
        sys.exit("Uso: ejecutar_mesa.py <" + "|".join(PERFILES) + ">")
    sys.exit(ejecutar(sys.argv[1]))
