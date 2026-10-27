"""Pruebas de los trabajos: ejecutor de mesas (con un Jira falso) y programador.

Ejecutar desde jobs/:   python3 -m unittest discover -s test -v
No usa red externa ni credenciales reales.
"""
import datetime as dt
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

import ejecutar_mesa  # noqa: E402
import programador  # noqa: E402

FIXTURE = json.loads((AQUI / "fixtures" / "interna.json").read_text(encoding="utf-8"))


class JiraFalso:
    """Servidor mínimo de POST /rest/api/3/search/jql con datos anonimizados de la mesa interna."""

    def __init__(self, sd=None, falla=0):
        self.sd = FIXTURE["sd"] if sd is None else sd
        self.sw = FIXTURE["sw"]
        self.falla = falla          # cuántas peticiones iniciales responden 500
        self.peticiones = []
        self.autorizaciones = set()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.peticiones.append((self.path, cuerpo["jql"]))
                outer.autorizaciones.add(self.headers.get("Authorization", ""))
                if outer.falla > 0:
                    outer.falla -= 1
                    self.send_response(500)
                    self.end_headers()
                    return
                datos = outer.sw if cuerpo["jql"].startswith("key in") else outer.sd
                out = json.dumps({"issues": datos, "isLast": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def cerrar(self):
        self.srv.shutdown()


class EjecutorMesa(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jira = None

    def env(self, jira):
        return {
            "PATH": "/usr/bin:/bin",
            "JIRA_SCITECH_URL": jira.url,
            "JIRA_SCITECH_EMAIL": "cuenta@ejemplo.test",
            "JIRA_SCITECH_TOKEN": "token-falso",
            "PUBLICADO_DIR": f"{self.tmp.name}/pub",
            "ESTADO_DIR": f"{self.tmp.name}/estado",
            "REINTENTOS": "2",
            "ESPERA_S": "0",
        }

    def jira_nuevo(self, **kw):
        j = JiraFalso(**kw)
        self.addCleanup(j.cerrar)
        return j

    def pagina(self):
        return Path(self.tmp.name, "pub", "mesas-interna", "index.html")

    def estado(self):
        return json.loads(Path(self.tmp.name, "estado", "interna_nueva.json").read_text())

    def test_publica_y_registra_estado(self):
        j = self.jira_nuevo()
        self.assertEqual(ejecutar_mesa.ejecutar("interna_nueva", self.env(j)), 0)
        html = self.pagina().read_text(encoding="utf-8")
        self.assertEqual(ejecutar_mesa.contar_filas(html), 10)
        self.assertEqual(self.estado()["solicitudes"], 10)
        self.assertNotIn("__DATA__", html)
        # consultó solicitudes de SCIMSI y luego las tareas vinculadas
        jqls = [q for _, q in j.peticiones]
        self.assertTrue(any("SCIMSI" in q for q in jqls))
        self.assertTrue(any(q.startswith("key in") for q in jqls))
        self.assertEqual(len(j.autorizaciones), 1)

    def test_reintenta_ante_error_de_jira(self):
        j = self.jira_nuevo(falla=1)
        self.assertEqual(ejecutar_mesa.ejecutar("interna_nueva", self.env(j)), 0)
        self.assertTrue(self.pagina().exists())

    def test_si_jira_falla_conserva_la_version_anterior(self):
        j = self.jira_nuevo()
        self.assertEqual(ejecutar_mesa.ejecutar("interna_nueva", self.env(j)), 0)
        antes = self.pagina().read_text(encoding="utf-8")
        j.falla = 99
        self.assertEqual(ejecutar_mesa.ejecutar("interna_nueva", self.env(j)), 1)
        self.assertEqual(self.pagina().read_text(encoding="utf-8"), antes)
        self.assertIn("ultimo_error", self.estado())
        self.assertEqual(self.estado()["solicitudes"], 10)  # el estado bueno no se pierde
        self.assertEqual([p.name for p in self.pagina().parent.iterdir()], ["index.html"])  # sin temporales

    def test_cuadre_rechaza_caida_brusca(self):
        j = self.jira_nuevo()
        self.assertEqual(ejecutar_mesa.ejecutar("interna_nueva", self.env(j)), 0)
        antes = self.pagina().read_text(encoding="utf-8")
        j.sd = FIXTURE["sd"][:5]
        self.assertEqual(ejecutar_mesa.ejecutar("interna_nueva", self.env(j)), 2)
        self.assertEqual(self.pagina().read_text(encoding="utf-8"), antes)
        self.assertIn("cuadre", self.estado()["ultimo_error"])

    def test_rechaza_tablero_vacio_en_primera_corrida(self):
        j = self.jira_nuevo(sd=[])
        self.assertEqual(ejecutar_mesa.ejecutar("interna_nueva", self.env(j)), 2)
        self.assertFalse(self.pagina().exists())

    def test_faltan_credenciales(self):
        j = self.jira_nuevo()
        env = self.env(j)
        del env["JIRA_SCITECH_TOKEN"]
        with self.assertRaises(SystemExit):
            ejecutar_mesa.ejecutar("interna_nueva", env)

    def test_salud360_usa_su_propio_sitio_y_sin_textos(self):
        env = {
            "JIRA_SALUD360_URL": "https://salud360.ejemplo.test/",
            "JIRA_SALUD360_EMAIL": "a@b.test",
            "JIRA_SALUD360_TOKEN": "t",
            "JIRA_SCITECH_URL": "https://scitech.ejemplo.test",
            "MODO_PUBLICO": "1",
        }
        e = ejecutar_mesa.entorno_generador("salud360", env)
        self.assertEqual(e["JIRA_SITE"], "https://salud360.ejemplo.test")
        self.assertEqual(e["JIRA_SITE_S360"], "https://salud360.ejemplo.test")
        self.assertEqual(e["INCLUIR_TEXTOS"], "0")
        self.assertNotIn("MODO_PUBLICO", e)


class Programador(unittest.TestCase):
    B = programador.BOGOTA
    FEST = {"2026": {"2026-11-02"}}

    def t(self, y, m, d, h, mi=0):
        return dt.datetime(y, m, d, h, mi, tzinfo=self.B)

    def test_dia_habil_dentro_del_horario(self):
        self.assertTrue(programador.debe_correr(self.t(2026, 10, 27, 6, 0), None, self.FEST))
        self.assertTrue(programador.debe_correr(self.t(2026, 10, 27, 19, 29), None, self.FEST))

    def test_fuera_de_horario(self):
        self.assertFalse(programador.debe_correr(self.t(2026, 10, 27, 5, 59), None, self.FEST))
        self.assertFalse(programador.debe_correr(self.t(2026, 10, 27, 19, 30), None, self.FEST))

    def test_fin_de_semana_y_festivo(self):
        self.assertFalse(programador.debe_correr(self.t(2026, 10, 31, 10), None, self.FEST))  # sábado
        self.assertFalse(programador.debe_correr(self.t(2026, 11, 1, 10), None, self.FEST))   # domingo
        self.assertFalse(programador.debe_correr(self.t(2026, 11, 2, 10), None, self.FEST))   # festivo (lunes)

    def test_intervalo(self):
        u = self.t(2026, 10, 27, 10, 0)
        self.assertFalse(programador.debe_correr(self.t(2026, 10, 27, 10, 29), u, self.FEST))
        self.assertTrue(programador.debe_correr(self.t(2026, 10, 27, 10, 30), u, self.FEST))

    def test_festivos_del_repo_traen_2026_y_formato_valido(self):
        f = programador.cargar_festivos()
        self.assertIn("2026", f)
        for d in f["2026"]:
            self.assertEqual(dt.date.fromisoformat(d).year, 2026)
        self.assertEqual(len(f["2026"]), 19)


if __name__ == "__main__":
    unittest.main()
