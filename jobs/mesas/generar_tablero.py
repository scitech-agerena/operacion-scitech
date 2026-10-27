#!/usr/bin/env python3
"""
Genera el tablero HTML de las mesas de servicio de Scitech a partir de Jira.

Uso normal (consulta Jira y escribe el HTML):
    JIRA_EMAIL=... JIRA_API_TOKEN=... python generar_tablero.py --salida public/index.html

Uso sin conexión (reconstruye desde respuestas de Jira ya guardadas en JSON):
    python generar_tablero.py --desde-archivos sd1.json sd2.json --sw sw1.json sw2.json --salida index.html

No usa librerías externas ni consume tokens de IA: solo la API de Jira.
Variables opcionales:
    JIRA_SITE          https://scitech.atlassian.net
    MODO_PUBLICO=1     omite el texto (resumen) de cada solicitud
    OCULTAR_PERSONAS=1 reemplaza los nombres de responsables por "Persona A, B, ..."
"""
import argparse, base64, datetime as dt, json, os, re, sys, urllib.request

PERFIL = os.environ.get("PERFIL", "vigentes")
if PERFIL == "interna_nueva":      # mesa interna NUEVA (SCIMSI + SMDSIS, todo el histórico): mismo perfil visual que interna
    PERFIL = "interna"
    os.environ.setdefault("PROYECTOS_INTERNA", "SCIMSI"); os.environ.setdefault("HISTORICO_INTERNA", "1"); os.environ.setdefault("TITULO_INTERNA", "Tablero Mesa de Servicio Interna")      # vigentes = mesas de clientes | interna = mesa de servicio interna (MSI/SCIMSI) | salud360 = mesa H360 (otra instancia)

# ---------------------------------------------------------------- configuración
SITE = os.environ.get("JIRA_SITE", "https://scitech.atlassian.net").rstrip("/")
# Alcance (clientes vigentes): TODAS las solicitudes (abiertas y cerradas) de los proyectos de la categoría "Proyectos Vigentes SD",
# y de la Mesa de Servicios General solo las de las organizaciones que tengan solicitudes sin cerrar.
GENERAL = "SMDSG"                      # mesa con muchos clientes
INTERNAS = "MSI, SCIMSI"               # mesas internas de Scitech: fuera del alcance
JQL_VIGENTES = f'projectCategory = "Proyectos Vigentes SD" AND project not in ({GENERAL}, {INTERNAS}) ORDER BY key ASC'
JQL_ORGS_ABIERTAS = f'project = {GENERAL} AND statusCategory != Done ORDER BY key ASC'   # solo para saber qué organizaciones
JQL_CERRADAS_ABIERTAS = 'projectCategory = "Proyectos Cerrados SD" AND statusCategory != Done ORDER BY key ASC'   # mesas fuera de la categoría vigente que aún tienen solicitudes sin cerrar (ej. EMPSOP)
JQL_GENERAL = f'project = {GENERAL} AND cf[10200] in ({{ids}}) ORDER BY key ASC'
F_ORG, F_SLA_RES, F_SLA_FRT = "customfield_10200", "customfield_10418", "customfield_10419"
FIELDS_SD = ["summary", "status", "priority", "issuelinks", F_SLA_RES, F_SLA_FRT, "resolutiondate",
             "customfield_10200", "created", "updated", "issuetype", "project", "reporter"]
FIELDS_SW = ["status", "assignee", "project", "created", "updated", "resolutiondate"]

# ---- Perfil "interna": mesa de servicio interna (MSI hoy, SCIMSI cuando reemplace a MSI). El eje no es el cliente sino el ÁREA que atiende.
DESDE_INTERNA = os.environ.get("DESDE_INTERNA", "2026-01-01")        # operación desde esta fecha + todo lo que siga abierto
# Dos tableros independientes (octubre 2026): PERFIL=interna = mesa ANTIGUA (solo MSI + tareas PRMSI); PERFIL=interna_nueva = mesa NUEVA (solo SCIMSI + tareas SMDSIS, todo el histórico).
PROYECTOS_INTERNA = os.environ.get("PROYECTOS_INTERNA", "MSI")
HISTORICO_INTERNA = os.environ.get("HISTORICO_INTERNA") == "1"       # 1 = todas las solicitudes del proyecto, sin filtro de fecha
TITULO_INTERNA = os.environ.get("TITULO_INTERNA", "Tablero Mesa Interna")
_FILTRO = "" if HISTORICO_INTERNA else f' AND (created >= "{DESDE_INTERNA}" OR statusCategory != Done)'
JQL_INTERNA = f'project in ({PROYECTOS_INTERNA}){_FILTRO} ORDER BY key ASC'
F_AREA = "customfield_10552"                                         # área que atiende en los Requerimientos (Admin-Talento Humano, Infraestructura, VCS, ...)
F_AREA_INC = "customfield_10686"                                     # el formulario de Incidencia guarda el área en este otro campo
FIELDS_INT = FIELDS_SD + [F_AREA, F_AREA_INC]
ETAPA_INTERNA = {"En espera": "cola", "Planeación": "cola"}          # PRMSI: Nueva / En espera / Planeación = cola; En progreso = en trabajo
PERFIL_INTERNA = {
    "horasViejo": 30,
    "estExtra": [["DEVUELTO", "#8a5a44"]], "tipoFiltro": True, "cruzTipo": True, "subtipo": True,
    "fuente": (("Fuente: Jira, mesa de servicio interna (proyecto " + PROYECTOS_INTERNA + "): todas las solicitudes desde su creación, con sus tareas vinculadas en Jira Software (SMDSIS). Las áreas son el campo “Área” de cada solicitud. " if HISTORICO_INTERNA else
               "Fuente: Jira, mesa de servicio interna antigua (proyecto MSI): solicitudes creadas desde " + DESDE_INTERNA[:4] +
               " y todas las que siguen abiertas, con sus tareas vinculadas en Jira Software (PRMSI). Las áreas son el campo “Área” de cada solicitud. ") +
               "Se actualiza una vez al día. “Resuelta” no tiene fecha propia en Jira: se usa la fecha de cierre de la tarea vinculada. ANS = acuerdo de nivel de servicio."),
}
# Texto del tablero adaptado a la mesa interna (se aplica solo a la plantilla, nunca a los datos).
LEXICO_INTERNA = [
    ("Por aclarar por el cliente", "\0PAC\0"),                      # nombre real de un estado: no se toca
    ("<title>Tablero Mesas de Servicio</title>", "<title>" + TITULO_INTERNA + "</title>"),
    ("<h1>Mesas de servicio</h1>", "<h1>Mesa de servicio interna</h1>"),
    ("Panorama de clientes vigentes", "Panorama de la mesa interna"),
    ("Todas las solicitudes, abiertas y cerradas, de las mesas de los clientes vigentes: los proyectos vigentes de mesa de servicio y las organizaciones de la Mesa General con solicitudes abiertas.",
     ("Solicitudes de la mesa interna (" + PROYECTOS_INTERNA.replace(",", " y") + ") " + ("de toda su historia" if HISTORICO_INTERNA else "creadas en el año en curso y todas las que siguen abiertas") + ", agrupadas por el área que las atiende.")),
    ("Todas las solicitudes de los clientes vigentes, con lo que sigue abierto.", "Requerimientos e incidencias, con lo que sigue abierto."),
    ("<dt>Clientes vigentes</dt><dd>Los clientes cuya mesa de servicio sigue vigente, más las organizaciones de la Mesa General que tienen solicitudes abiertas. Todo el tablero trabaja sobre sus solicitudes, abiertas y cerradas.</dd>",
     "<dt>Área</dt><dd>El área de Scitech que atiende la solicitud (campo “Área”): Talento Humano, Infraestructura, VCS, Salud360, Calidad, Desarrollo… Las solicitudes sin área aparecen como “Sin área”.</dd>"),
    ("o Cliente (espera su respuesta o confirmación)", "o Solicitante (espera su respuesta o confirmación)"),
    ("falta responder al cliente o cerrarla", "falta responder al solicitante o cerrarla"),
    ('cli:["Cliente","var(--cli)"]', 'cli:["Solicitante","var(--cli)"]'),
    ('[x.cli,"var(--cli)","Cliente"]', '[x.cli,"var(--cli)","Solicitante"]'),
    ("Esperando al cliente", "Esperando al solicitante"), ("Responder al cliente o resolver", "Responder al solicitante o resolver"),
    (" Los clientes se nombran con la clave de la mesa.", ""), ("los clientes", "las áreas"), ("Los clientes", "Las áreas"), ("los Clientes", "las Áreas"),
    ("Cliente: todos", "Área: todas"), ("todos los clientes", "todas las áreas"),
    ("Los clientes se nombran con la clave de la mesa y la organización", "Las áreas son las del campo “Área”"),
    ("Cliente por tipo de solicitud", "Área por tipo de solicitud"), ("Cuántas solicitudes tiene cada cliente", "Cuántas solicitudes tiene cada área"),
]
def adaptar_plantilla(html):
    for a, b in LEXICO_INTERNA:
        html = html.replace(a, b)
    html = re.sub(r"(?<![\w.])Clientes(?![\w.=_(\[])", "Áreas", html)
    html = re.sub(r"(?<![\w.])Cliente(?![\w.=_(\[])", "Área", html)
    html = re.sub(r"(?<![\w.])clientes(?![\w.=_(\[])", "áreas", html)
    html = re.sub(r"(?<![\w.])cliente(?![\w.=_(\[])", "área", html)
    return html.replace("\0PAC\0", "Por aclarar por el cliente")

# ---- Perfil "salud360": una sola mesa (H360, instancia salud360.atlassian.net), sin Jira Software. Escala a desarrollo mediante un enlace a una tarea de Scitech.
SITE_S360 = os.environ.get("JIRA_SITE_S360", "https://salud360.atlassian.net").rstrip("/")
SITE_ESC = "https://scitech.atlassian.net/browse/"                    # las tareas de desarrollo (S360SC) viven en la instancia de Scitech
JQL_S360 = os.environ.get("JQL_S360") or 'project = H360 AND (created >= -365d OR statusCategory != Done) ORDER BY key ASC'
F_S360 = {"org": "customfield_10002", "modulo": "customfield_10152", "esc": "customfield_10159", "rech": "customfield_10166", "res": "customfield_10148", "frt": "customfield_10134"}
FIELDS_S360 = ["summary", "status", "priority", "issuetype", "created", "updated", "resolutiondate", "assignee", "reporter", "project"] + list(F_S360.values())
INCLUIR_TEXTOS = os.environ.get("INCLUIR_TEXTOS", "0") == "1"        # por defecto NO se publica el resumen de las solicitudes (datos de salud / hospitales)
PRIO_ES = {"Highest": "Alta", "High": "Alta", "Medium": "Mediana", "Low": "Baja", "Lowest": "Baja"}
TIPO_ES = {"Nueva Caracteristica": "Nueva característica"}
MODULOS = [   # (nombre, expresiones regulares sobre el texto libre del campo Módulo, en minúsculas y sin tildes); gana la primera que coincida
    ("Interoperabilidad", [r"interoper", r"fhir", r"\bapi\b", r"integracion", r"web ?service", r"\bihce\b", r"interfaz", r"\bjson\b"]),
    ("Facturación", [r"factur", r"radicac", r"\brips\b", r"glosa", r"dian", r"\bcups\b", r"nota(s)? (credito|debito|tecnica)"]),
    ("Contabilidad", [r"contab", r"activos fijos", r"libro", r"tributar", r"impuesto", r"financier", r"\bcaja\b"]),
    ("Presupuesto", [r"presupu"]), ("Cartera", [r"cartera", r"recaudo", r"cobro"]), ("Tesorería y nómina", [r"tesor", r"nomin", r"pagos", r"bancos"]),
    ("Inventarios y farmacia", [r"inventar", r"farmac", r"almacen", r"suministro", r"dispens", r"medicament", r"generico", r"bodega", r"despacho", r"producto", r"remision"]),
    ("Historia clínica", [r"historia", r"clinic", r"\bhc\b", r"evoluci", r"formula", r"ordenamiento", r"ordenes", r"notas aclaratorias", r"diagnostic"]),
    ("Citas y agenda", [r"\bcita", r"agenda", r"programacion"]), ("Laboratorio e imágenes", [r"laborat", r"imagen", r"rayos", r"toma de muestras"]),
    ("Informes", [r"informe", r"reporte"]), ("Auditoría", [r"auditor", r"auditar"]), ("Contratación", [r"contrat", r"convenio"]),
    ("Atención en salud", [r"asistencial", r"hospital", r"urgencia", r"cirug", r"enfermer", r"triage", r"admision", r"psicolog", r"psiquiatr", r"odontolog",
                           r"valoracion", r"consulta", r"procedimiento", r"actividades grupales", r"atenciones", r"\bpad\b", r"eventos adversos", r"ingreso", r"call center"]),
    ("Pacientes y usuarios", [r"paciente", r"usuario", r"afiliad", r"tercero", r"perfil", r"permiso", r"acceso"]),
    ("Seguridad y plataforma", [r"servidor", r"base de datos", r"backup", r"licencia", r"instalacion", r"actualizacion", r"\bred\b", r"seguridad", r"inicio de sesion",
                                r"plataforma", r"administrador", r"firma electronica", r"caida", r"lentitud", r"\bfalla", r"\berror", r"ambiente de prueba", r"infraestructura"]),
    ("General", [r"^(salud ?)?360$", r"^salud$", r"^todos", r"general", r"administra", r"problemas?$"]),
]
def sin_tildes(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
def modulo(txt):
    t = sin_tildes((txt or "").lower()).strip()
    if not t or t in ("none", "n/a", "na", "-", "."):
        return "Sin módulo"
    for nombre, claves in MODULOS:
        if any(re.search(c, t) for c in claves):
            return nombre
    return "Otros"
PERFIL_S360 = {
    "sinSW": True, "modFiltro": True, "rechazadas": True, "skSite": SITE_ESC,
    "est": [["En curso", "var(--e1)"], ["En Desarrollo", "var(--e2)"], ["Por Aclarar Por Scitech", "var(--e3)"], ["Por aclarar por el cliente", "var(--e4)"],
            ["Por aclarar por el proveedor", "#2aa5a0"], ["Resuelto", "var(--e5)"]],
    "fuente": ("Fuente: Jira, mesa HelpDesk Salud360 (proyecto H360): solicitudes de los últimos 12 meses y todas las que siguen abiertas. Una sola mesa, sin Jira Software: "
               "una solicitud se cuenta como escalada a desarrollo cuando tiene enlazada una tarea de Scitech. El módulo es texto libre agrupado por palabras clave. "
               "Se actualiza una vez al día. ANS = acuerdo de nivel de servicio."),
}
LEXICO_S360 = [
    ("<title>Tablero Mesas de Servicio</title>", "<title>Tablero Salud 360</title>"),
    ("<h1>Mesas de servicio</h1>", "<h1>Mesa de servicio Salud 360</h1>"),
    ("Panorama de clientes vigentes", "Panorama de Salud 360"),
    ("Todas las solicitudes, abiertas y cerradas, de las mesas de los clientes vigentes: los proyectos vigentes de mesa de servicio y las organizaciones de la Mesa General con solicitudes abiertas.",
     "Solicitudes de la mesa HelpDesk Salud360 de los últimos 12 meses y todas las que siguen abiertas, por institución cliente."),
    ("Todas las solicitudes de los clientes vigentes, con lo que sigue abierto.", "Soporte, nuevas características y problemas, con lo que sigue abierto."),
    ("<dt>Clientes vigentes</dt><dd>Los clientes cuya mesa de servicio sigue vigente, más las organizaciones de la Mesa General que tienen solicitudes abiertas. Todo el tablero trabaja sobre sus solicitudes, abiertas y cerradas.</dd>",
     "<dt>Módulo</dt><dd>Módulo del aplicativo al que se refiere la solicitud. Es un campo de texto libre; el tablero lo agrupa por palabras clave y las solicitudes sin dato aparecen como “Sin módulo”.</dd>"),
    ("Software Scitech", "Desarrollo / proveedor"), ("Mesa Scitech", "Mesa Salud 360"),
    ("Sin movimiento en la mesa ni en Software", "Sin movimiento en la mesa ni en desarrollo"),
    ("en la solicitud ni en su tarea de Software", "en la solicitud ni en su tarea de desarrollo"),
    ("Solicitud que pasó a una tarea en Jira Software.", "Solicitud con una tarea de desarrollo de Scitech enlazada."),
    ("ANS vencido, Software ya cerró pero la solicitud sigue abierta, y resueltas hace más de 60 días.", "ANS vencido, escaladas a desarrollo sin cerrar, y resueltas hace más de 60 días."),
    ("pasaron a una tarea en Jira Software", "se escalaron a desarrollo"),
]
def adaptar_s360(html):
    for a, b in LEXICO_S360:
        html = html.replace(a, b)
    return html
MODO_PUBLICO = os.environ.get("MODO_PUBLICO", "0") == "1"
OCULTAR_PERSONAS = os.environ.get("OCULTAR_PERSONAS", "0") == "1"

# Nombres de cliente más legibles (si falta alguno se usa el nombre de la organización tal cual).
CLIENTE = {
    "BANMIA - Banca Móvil": "BANMIA Banca Móvil", "SD EMPAS SOPORTE CONTRATO 5820": "EMPAS · contrato 5820",
    "GARANTISA MESA DE AYUDA-GAR-SM25": "Garantisa · SM25", "AVANZAR FOS": "Avanzar FOS",
    "ALCALDÍA BUCARAMANGA 2026 SD": "Alcaldía de Bucaramanga", "FRIGORÍFICO GUADALUPE": "Frigorífico Guadalupe",
    "Garantisa soporte 2023 SD": "Garantisa · soporte 2023",
    "Cooprofesores – Contabilidad y Activos Fijos 2026 SD": "Cooprofesores · Contabilidad",
    "Nom Cooprofesores": "Cooprofesores · Nómina", "COOPFUTURO": "Coopfuturo",
    "Efectimedios Soporte": "Efectimedios · soporte", "SD EFECTIMEDIOS SOPORTE 2026": "Efectimedios 2026",
    "SOPORTE FGS": "FGS soporte", "Soporte Operación GAR-PTF2": "Garantisa · PTF2", "Soporte Garantía Total": "Garantía Total",
    "Mesa de Ayuda EMPAS (2023-2024)": "EMPAS · 2023-2024", "EMPAS": "EMPAS · 2023-2024",
    "Servicio de Soporte y Mantenimiento para EMPAS (2023-2024)": "EMPAS · 2023-2024",
}
# Estado de la tarea en Jira Software -> etapa. Los estados nuevos caen en "curso" hasta que se agreguen aquí.
ETAPA_SW = {
    "Cerrado": "cerr", "PRUEBAS UAT": "uat", "Prueba UAT": "uat", "UAT finalizado": "uat", "Despliegue": "uat",
    "Nueva": "cola", "Aprobada": "cola", "En espera análisis": "cola", "Análisis en aprobación": "cola",
}

# ---------------------------------------------------------------- Jira
def _request(path, body):
    email, token = os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"]
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    req = urllib.request.Request(SITE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def buscar(jql, fields):
    """Pagina /rest/api/3/search/jql hasta agotar resultados."""
    out, token = [], None
    while True:
        body = {"jql": jql, "fields": fields, "maxResults": 100}
        if token:
            body["nextPageToken"] = token
        data = _request("/rest/api/3/search/jql", body)
        out += data.get("issues", [])
        token = data.get("nextPageToken")
        if not token or data.get("isLast"):
            return out

def traer_de_jira():
    if PERFIL == "salud360":
        return buscar(JQL_S360, FIELDS_S360), []
    if PERFIL == "interna":
        sd = buscar(JQL_INTERNA, FIELDS_INT)
        claves = sorted({k for i in sd for k in enlaces(i["fields"])})
        sw = []
        for n in range(0, len(claves), 80):
            sw += buscar("key in (" + ",".join(claves[n:n + 80]) + ")", FIELDS_SW)
        return sd, sw
    sd = buscar(JQL_VIGENTES, FIELDS_SD)
    pk = sorted({i["key"].rsplit("-", 1)[0] for i in buscar(JQL_CERRADAS_ABIERTAS, ["project"])})
    if pk:
        sd += buscar("project in (" + ",".join(pk) + ") ORDER BY key ASC", FIELDS_SD)
    orgs = {o["id"] for i in buscar(JQL_ORGS_ABIERTAS, ["customfield_10200"]) for o in (i["fields"].get(F_ORG) or [])}
    if orgs:
        sd += buscar(JQL_GENERAL.format(ids=",".join(sorted(orgs, key=int))), FIELDS_SD)
    claves = sorted({k for i in sd for k in enlaces(i["fields"])})
    sw = []
    for n in range(0, len(claves), 80):
        sw += buscar("key in (" + ",".join(claves[n:n + 80]) + ")", FIELDS_SW)
    return sd, sw

def leer_archivo(ruta):
    """Acepta tanto la respuesta REST (issues: [...]) como la del conector MCP (issues: {nodes: [...]})."""
    d = json.load(open(ruta, encoding="utf-8"))
    iss = d.get("issues", d)
    return iss.get("nodes", []) if isinstance(iss, dict) else iss

# ---------------------------------------------------------------- transformación
def utc(s):
    if not s:
        return None
    s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s)          # -0500 -> -05:00
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def enlaces(f):
    """Claves de las tareas de Software vinculadas (primero Problem/Incident)."""
    L = [(l["type"]["name"], (l.get("inwardIssue") or l.get("outwardIssue"))["key"]) for l in f.get("issuelinks", [])]
    L.sort(key=lambda x: x[0] != "Problem/Incident")
    return [k for _, k in L]

def ciclo(sla):
    """Ciclo vigente o, si ya terminó, el último completado."""
    if not sla:
        return None
    return sla.get("ongoingCycle") or (sla.get("completedCycles") or [None])[-1]

def medida(sla, c):
    """1 si el ANS ya se puede medir: ciclo terminado o ya incumplido (un ciclo en curso sin vencer aún no cuenta)."""
    return int(bool(c) and (not (sla or {}).get("ongoingCycle") or bool(c.get("breached"))))

EXTRA_S360 = {}
def construir_s360(sd):
    filas = []
    for i in sd:
        f, k = i["fields"], i["key"]
        orgs = f.get(F_S360["org"]) or []
        org = re.sub(r"\s+20\d\d$", "", (orgs[0]["name"] if orgs else "Sin organización").strip())
        m = re.search(r"browse/([A-Z][A-Z0-9]+-\d+)", str(f.get(F_S360["esc"]) or ""))
        sk = m.group(1) if m else None
        est = (f["status"]["name"] or "").replace("SCITECH", "Scitech")
        rj = f.get(F_S360["rech"]) if F_S360["rech"] in f else EXTRA_S360.get(k, {}).get(F_S360["rech"])
        rj = int((rj.get("value") if isinstance(rj, dict) else rj) == "Si")
        r, fr = ciclo(f.get(F_S360["res"])) or {}, ciclo(f.get(F_S360["frt"])) or {}
        ms = lambda c, n: (c.get(n) or {}).get("millis", 0)
        t = f["issuetype"]["name"]
        filas.append({
            "k": k, "s": (f.get("summary") or "").strip() if (INCLUIR_TEXTOS and not MODO_PUBLICO) else "",
            "p": "HelpDesk Salud360", "t": TIPO_ES.get(t, t), "e": est, "c": utc(f["created"]), "u": utc(f["updated"]), "rs": utc(f.get("resolutiondate")),
            "cl": org, "pr": PRIO_ES.get((f.get("priority") or {}).get("name", ""), "Sin prioridad"),
            "mo": modulo(f.get(F_S360["modulo"])), "rj": rj, "as": ((f.get("assignee") or {}).get("displayName")) or "",
            "rb": int(bool(r.get("breached"))), "rp": int(bool(r.get("paused"))),
            "rg": ms(r, "goalDuration"), "rl": ms(r, "elapsedTime"), "rm": ms(r, "remainingTime"),
            "fb": int(bool(fr.get("breached"))), "fe": ms(fr, "elapsedTime"),
            "rx": medida(f.get(F_S360["res"]), r), "fx": medida(f.get(F_S360["frt"]), fr), "rq": "" if OCULTAR_PERSONAS else ((f.get("reporter") or {}).get("displayName") or ""),
            "sk": sk, "ss": "Escalada a desarrollo" if sk else "", "sb": "curso" if sk else "none", "sa": None,
            "sj": "", "sd": None, "su": None, "sc": None,
        })
    return filas

def construir(sd, sw):
    if PERFIL == "salud360":
        return construir_s360(sd)
    swd = {i["key"]: i["fields"] for i in sw}
    filas = []
    for i in sd:
        f, k = i["fields"], i["key"]
        ks = [x for x in enlaces(f) if x in swd]
        s = swd[ks[0]] if ks else {}
        sk = ks[0] if ks else None
        sn = (s.get("status") or {}).get("name", "")
        orgs = f.get(F_ORG) or []
        org = orgs[0]["name"] if orgs else re.sub(r"\s+", " ", f["project"]["name"]).strip()
        area = next((f[c]["value"] for c in (F_AREA, F_AREA_INC) if isinstance(f.get(c), dict) and f[c].get("value")), None)
        sub = ""
        for c in (F_AREA, F_AREA_INC):
            v = f.get(c)
            if isinstance(v, dict) and v.get("value") and PERFIL == "interna":
                hijo = ((v.get("child") or {}).get("value") or "").strip()
                sub = f'{v["value"]} · {hijo}' if hijo else v["value"]
                break
        etiqueta = (area or "Sin área") if PERFIL == "interna" else (f'{f["project"].get("key", "")} · {CLIENTE.get(org, org)}' if f["project"].get("key") else CLIENTE.get(org, org))
        r, fr = ciclo(f.get(F_SLA_RES)) or {}, ciclo(f.get(F_SLA_FRT)) or {}
        ms = lambda c, n: (c.get(n) or {}).get("millis", 0)
        filas.append({
            "k": k, "s": "" if MODO_PUBLICO else (f.get("summary") or "").strip(),
            "p": re.sub(r"\s+", " ", f["project"]["name"]).strip(), "t": f["issuetype"]["name"],
            "e": f["status"]["name"], "c": utc(f["created"]), "u": utc(f["updated"]), "rs": utc(f.get("resolutiondate")),
            "cl": etiqueta, "pr": (f.get("priority") or {}).get("name", "Sin prioridad"),
            "rb": int(bool(r.get("breached"))), "rp": int(bool(r.get("paused"))),
            "rg": ms(r, "goalDuration"), "rl": ms(r, "elapsedTime"), "rm": ms(r, "remainingTime"),
            "fb": int(bool(fr.get("breached"))), "fe": ms(fr, "elapsedTime"),
            "rx": medida(f.get(F_SLA_RES), r), "fx": medida(f.get(F_SLA_FRT), fr),
            "sub": sub,
            "rq": "" if OCULTAR_PERSONAS else ((f.get("reporter") or {}).get("displayName") or ""),
            "sk": sk, "ss": sn, "sb": {**ETAPA_SW, **(ETAPA_INTERNA if PERFIL == "interna" else {})}.get(sn, "curso") if sk else "none",
            "sa": ((s.get("assignee") or {}).get("displayName")) if sk else None,
            "sj": re.sub(r"\s+", " ", (s.get("project") or {}).get("name", "")).strip(),
            "sd": utc(s.get("resolutiondate")), "su": utc(s.get("updated")), "sc": utc(s.get("created")),
        })
    if OCULTAR_PERSONAS:
        nombres = sorted({x["sa"] for x in filas if x["sa"]})
        letra = {n: f"Persona {chr(65 + j) if j < 26 else j + 1}" for j, n in enumerate(nombres)}
        for x in filas:
            x["sa"] = letra.get(x["sa"])
    return filas

# ---------------------------------------------------------------- salida
def renderizar(filas, plantilla, ahora):
    html = open(plantilla, encoding="utf-8").read()
    if PERFIL == "interna":
        html = adaptar_plantilla(html)
    elif PERFIL == "salud360":
        html = adaptar_s360(html)
    else:  # vigentes (Clientes)
        html = html.replace("<title>Tablero Mesas de Servicio</title>", "<title>Mesas de Servicio Clientes Scitech</title>").replace("<h1>Mesas de servicio</h1>", "<h1>Mesas de Servicio Clientes Scitech</h1>")
    html = html.replace("__SITE__", (SITE_S360 if PERFIL == "salud360" else SITE) + "/browse/")
    datos = json.dumps(filas, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (html.replace("__DATA__", datos).replace("__GEN__", ahora.strftime("%Y-%m-%dT%H:%M:%SZ"))
                .replace("__PUBLICO__", "true" if MODO_PUBLICO else "false")
                .replace("__PERFIL__", json.dumps({"interna": PERFIL_INTERNA, "salud360": PERFIL_S360}.get(PERFIL, {}), ensure_ascii=False)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="index.html")
    ap.add_argument("--plantilla", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "plantilla.html"))
    ap.add_argument("--desde-archivos", nargs="*", help="respuestas JSON de solicitudes de la mesa")
    ap.add_argument("--sw", nargs="*", help="respuestas JSON de tareas de Software")
    ap.add_argument("--extra", help="JSON {clave: {campo: valor}} con campos adicionales (pruebas sin conexión)")
    ap.add_argument("--ahora", help="fecha de corte ISO (solo pruebas)")
    a = ap.parse_args()
    if a.desde_archivos:
        sd = [i for p in a.desde_archivos for i in leer_archivo(p)]
        sw = [i for p in (a.sw or []) for i in leer_archivo(p)]
    else:
        sd, sw = traer_de_jira()
    ahora = dt.datetime.fromisoformat(a.ahora.replace("Z", "+00:00")) if a.ahora else dt.datetime.now(dt.timezone.utc)
    if a.extra:
        EXTRA_S360.update(json.load(open(a.extra, encoding="utf-8")))
    filas = construir(sd, sw)
    os.makedirs(os.path.dirname(os.path.abspath(a.salida)), exist_ok=True)
    open(a.salida, "w", encoding="utf-8").write(renderizar(filas, a.plantilla, ahora))
    print(f"{len(filas)} solicitudes, {len(sw)} tareas de Software -> {a.salida}", file=sys.stderr)

if __name__ == "__main__":
    main()
