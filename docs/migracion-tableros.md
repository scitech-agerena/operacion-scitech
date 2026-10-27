# Migración de los tableros existentes

Inventario de lo que hoy producen los artefactos de Claude y de lo que hay que construir para que corran en el servidor. Cifras al 26 de octubre de 2026.

## 1. Alcance

| Tablero | Migrar | Nota |
|---|---|---|
| Mesas de Servicio Clientes Scitech (`vigentes`) | Sí | 2.858 solicitudes, 355 abiertas |
| Mesa de Servicio Interna (`interna_nueva`, SCIMSI + SMDSIS) | Sí | 45 solicitudes, 23 abiertas |
| Mesa de Servicio Salud 360 (`salud360`, H360) | Sí | 7.267 solicitudes, 333 abiertas |
| Tablero de Colaboradores | Sí | 77 personas, 168 proyectos, 68.485 h en 2026 |
| Mesa Interna antigua (`interna`, MSI + PRMSI) | **No** (propuesta) | 17 abiertas; se apaga cuando cierre sus tareas |
| Informes de proyecto (Garantisa SM25, FRGTRD2026) | No | Los gestiona cada PM |

## 2. Hallazgo que define la arquitectura

Los generadores actuales son Python estándar, sin librerías externas y **sin IA**: `generar_tablero.py` ya sabe consultar Jira (`/rest/api/3/search/jql`) con un correo y un token, y la plantilla HTML hace todos los cálculos en el navegador a partir de filas crudas incrustadas (`__DATA__`). Lo mismo aplica a Colaboradores (`actualizar.py`, `build_data.py`, `armar.py`).

Hoy Claude solo hace de "mensajero": consulta Jira por el conector, guarda los resultados y llama a esos scripts. En el servidor ese mensajero se reemplaza por una tarea programada.

**Arquitectura propuesta:** un contenedor Python con cron ejecuta los generadores existentes y deja el HTML en una carpeta que Caddy sirve detrás del login de Google. Las plantillas y los cálculos no se reescriben.

> El piloto de `api/` (Node, resumen de mesas calculado en el servidor) se hizo antes de conocer los generadores y **no replica** estos tableros. Se conserva por su capa de acceso por rol (`/api/me`) y como base para tableros futuros; los cálculos de las mesas siguen viviendo en la plantilla.

## 3. Inventario: mesas de servicio

Los tres comparten generador (`generar_tablero.py`, perfil por variable `PERFIL`) y plantilla (`plantilla.html`, ~140 KB).

| | `vigentes` | `interna_nueva` | `salud360` |
|---|---|---|---|
| Sitio Jira | scitech.atlassian.net | scitech.atlassian.net | salud360.atlassian.net |
| Consulta | Categoría «Proyectos Vigentes SD» sin MSI/SCIMSI; mesa general SMDSG solo de organizaciones con solicitudes sin cerrar; proyectos de «Proyectos Cerrados SD» con solicitudes sin cerrar (hoy EMPSOP) | `project = SCIMSI` (todo el histórico) | `project = H360 AND (created >= -365d OR statusCategory != Done)` |
| Tareas vinculadas | Jira Software, por `issuelinks`, en lotes de 80 | SMDSIS, igual | No hay; escalada = enlace a tarea S360SC de Scitech |
| Volumen de datos | ~8 MB | ~0,14 MB | ~11,7 MB |
| Foco | Cliente (organización) | Área que atiende | Institución cliente y módulo |

**Campos de Jira (solicitud):** `summary, status, priority, issuelinks, resolutiondate, created, updated, issuetype, project, reporter`, organización (`customfield_10200`), ANS de solución (`customfield_10418`) y de primera respuesta (`customfield_10419`). La interna añade el área (`customfield_10552` en requerimientos, `customfield_10686` en incidencias).

**Campos de Salud 360:** organización `customfield_10002`, módulo `customfield_10152` (texto libre, agrupado por palabras clave en el generador), enlace a desarrollo `customfield_10159`, rechazada `customfield_10166`, ANS solución `customfield_10148`, ANS primera respuesta `customfield_10134`.

**Campos de la tarea de Software:** `status, assignee, project, created, updated, resolutiondate`.

**Contrato de datos (una fila por solicitud, lo que consume la plantilla):**
`k` clave · `s` resumen · `p` proyecto · `t` tipo · `e` estado · `c` creada · `u` actualizada · `rs` resuelta · `cl` cliente o área · `pr` prioridad · ANS solución `rb rp rg rl rm` (incumplido, pausado, meta, transcurrido, restante) · ANS primera respuesta `fb fe` · medibles `rx fx` · `sub` subárea · `rq` solicitante · tarea vinculada `sk ss sb sa sj sd su sc` (clave, estado, etapa, responsable, proyecto, cerrada, actualizada, creada). Salud 360 añade `mo` módulo, `rj` rechazada, `as` asignado.

**Cálculos en la plantilla:** estados y antigüedad (umbrales 30, 15, 60 y 90 días), ANS (cumple ÷ medidas; solución 85 %, primera respuesta 95 %), pestaña Indicadores (% de cierre del periodo y acumulado, filtro año/mes, serie mensual, vista por cliente o área), relación solicitud ↔ tarea de Software, aviso de datos viejos (`horasViejo`: 10 h, 30 h en la interna).

**Actualización actual (Claude, lunes a viernes sin festivos):** 6:10 interna antigua · 6:20 interna nueva (completa) · 6:30 vigentes y Salud 360 (parcial, con extracción completa semanal).

## 4. Inventario: Tablero de Colaboradores

| Elemento | Hoy |
|---|---|
| Fuente | scitech.atlassian.net, Jira Software; proyectos listados en `proyectos.json` (168, incluye GESTDEV y PMOGDP) |
| Campos | `project, issuetype, status, priority, assignee, duedate, created, updated, resolutiondate, timeoriginalestimate, timespent, timeestimate, worklog` |
| Consultas | incremental (`updated >= corte − 2 días`), lunes: refuerzo de 8 días y foto de abiertas, día 1–2: mes anterior completo, siempre: proyecto PROAUS (ausencias) |
| Ausencias (PROAUS) | `customfield_11327` colaborador, `11328` tipo, `11329` recuperable, `10660` horas, `10414` inicio, `duedate`, `11332` resolución; 239 registros |
| Persistencia | `datos/horas_AAAA-MM.jsonl`, `tareas_AAAA-MM.jsonl`, `abiertas.jsonl`, `ausencias.jsonl` (≈1,7 MB en total); es el histórico del año |
| Configuración | `personas.json` (77: nombre, correo, área, mostrar, salida, tipo contratista), `proyectos.json` |
| Salida | `data.json` compacto incrustado en la plantilla; todos los cálculos (capacidad, utilización, ausencias, festivos de Colombia) se hacen en el navegador |
| Reglas | 44 h/semana hasta el 14 jul 2026 y 42 h desde el 15 jul; contratistas fuera de la capacidad; utilización: óptimo 95 %, aceptable 85 % |
| Controles al armar | las horas no bajan; las abiertas no cambian más de 15 %; mismo número de personas y proyectos |
| Limitación | 22 tareas con más de 20 registros de horas llegan truncadas y hoy solo se recuperan desde el navegador |

## 5. Qué hay que construir

**Mesas**
1. Imagen `python:3.12-slim` con `generar_tablero.py` y `plantilla.html` sin cambios, y un envoltorio por perfil que fije `PERFIL`, `JIRA_SITE`, `JIRA_EMAIL` y `JIRA_API_TOKEN`.
2. Corregir un fallo del modo directo: para el perfil `salud360` el generador consulta `JIRA_SITE` (Scitech) en lugar de `JIRA_SITE_S360`. El envoltorio debe fijar `JIRA_SITE=https://salud360.atlassian.net` con las credenciales de ese sitio.
3. Extracción **completa** en cada corrida. Con eso desaparece la lógica parcial y el problema de SMDSG. Medir el tiempo real (Salud 360 son ~73 páginas de 100).
4. Escribir a un archivo temporal y renombrar al terminar; si Jira falla, conservar la última versión buena y no publicar.
5. Control de cuadre antes de publicar (solicitudes no bajan, abiertas con variación razonable) y mantener `INCLUIR_TEXTOS=0` en Salud 360.
6. Frecuencia: sin costo de tokens deja de tener sentido una sola vez al día; proponer cada 30 a 60 minutos en horario laboral, con espera y reintento ante límites de Jira.

**Colaboradores**
1. Nuevo `extraer.py` que reemplace al conector: pagina por `nextPageToken`, pide los campos exactos y entrega el resultado envuelto como `{"issues":{"nodes":[...]}}` para reutilizar `actualizar.py` y `ausencias.py` sin cambios.
2. Recuperar los registros truncados con `/rest/api/3/issue/{clave}/worklog`, lo que elimina la lista de pendientes.
3. Volumen persistente para `datos/` con copia de seguridad: es el histórico que debe sobrevivir a 2027.
4. Generalizar lo fijado a 2026 (`D0`, `FIN`, `CHG`, `FEST`, `startswith('2026')`, `horas_2026-*`) antes de la primera corrida de enero.
5. Mantener `personas.json`, `proyectos.json` y `datos/` **fuera de Git** (datos de personas).
6. Programación: diaria 6:00 a. m., con los refuerzos de lunes y de inicio de mes.

**Acceso (ambos)**
- Mesas: solo roles internos (comité, PM, líderes). Las plantillas incrustan **todos** los clientes, resúmenes y solicitantes; un cliente externo nunca debe tener acceso.
- Colaboradores: comité y líderes de área.
- La carpeta publicada se sirve detrás de oauth2-proxy; la verificación por rol usa la misma lista de `api/config/access.json`.

## 6. Decisiones pendientes

1. **Interna antigua:** no migrarla (17 abiertas) y apagarla al cerrar. ¿Se confirma?
2. **Frecuencia** de actualización de cada tablero.
3. **Ausencias en Colaboradores:** hoy se muestran por persona y por tipo, incluida la incapacidad (3 casos). Opciones: mostrar solo horas descontadas, o agrupar los tipos médicos y legales en una sola categoría.
4. **Cuentas de servicio** de Jira de solo lectura, una por sitio, con visibilidad sobre todos los proyectos incluidos (entre ellos GESTDEV, PMOGDP y PROAUS).
5. **Respaldo** del volumen de datos y retención.

## 7. Riesgos

- **Límites y tiempo de Jira:** extracciones completas cada pocos minutos pueden toparse con límites de la API; hay que medir y escalonar las corridas.
- **Datos personales (Ley 1581):** las mesas contienen solicitantes y resúmenes; Colaboradores contiene nombres, horas y ausencias. Registrar el tratamiento en el SGSI.
- **Dependencia de Google Fonts** en las plantillas: aceptable, o autoalojar las tipografías si se quiere evitar la llamada externa.
- **Doble escritura:** mientras convivan los artefactos y el servidor, desactivar las tareas de Claude solo después de comparar resultados.

## 8. Orden y aceptación

Orden: mesa interna → Salud 360 → clientes vigentes → colaboradores.

Cada tablero pasa por **una semana en paralelo**. Criterio: coinciden el total de solicitudes, las abiertas y los porcentajes de ANS y de cierre (mesas), y las horas totales, las personas y la capacidad por área (colaboradores). Solo entonces se apaga la tarea programada de Claude correspondiente.

## 9. Estado de la migración

**Regla vigente:** los tableros y tareas programadas actuales en Claude **no se modifican**. El servidor corre en paralelo una semana y la decisión de apagar lo de Claude es de Albert.

| Tablero | Estado |
|---|---|
| Mesa interna (`interna_nueva`) | Construido y probado sin conexión. Falta la corrida real en el servidor |
| Salud 360 | Pendiente (el ejecutor ya fija el sitio correcto y `INCLUIR_TEXTOS=0`) |
| Clientes vigentes | Pendiente (el ejecutor ya lo contempla) |
| Colaboradores | Pendiente |

**Mesa interna, lo que hay en `jobs/`:**
- `mesas/generar_tablero.py` y `mesas/plantilla.html`: copias **sin cambios** de las del artefacto actual.
- `ejecutar_mesa.py`: consulta Jira, reintenta, valida el cuadre (las solicitudes no bajan más de 5 %), publica de forma atómica y conserva la última versión buena si algo falla.
- `programador.py`: cada 30 min, lunes a viernes sin festivos, de 6:00 a 19:30 (Bogotá). Festivos en `config/festivos.json`; **agregar 2027 antes de diciembre**.
- Acceso: Caddy consulta `/api/authz/mesas-interna` antes de entregar la página (comité, PM y líderes; los clientes externos reciben 403).

**Verificación hecha:** regenerando sin conexión con los datos reales del 26 oct, las 45 solicitudes y todos sus campos coinciden con el artefacto actual (0 diferencias). 12 pruebas de `jobs/` (`python3 -m unittest discover -s test`) y 13 de `api/` (`npm test`).

**Sin verificar todavía:** `Caddyfile` y `docker-compose.yml` no se han ejecutado (no hay Caddy ni Docker en el entorno de desarrollo); la primera prueba real es en Contabo con `docker compose config` y luego `up`.
