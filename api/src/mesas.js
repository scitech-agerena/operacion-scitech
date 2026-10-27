import { searchIssues } from './jira.js';

export const MESAS_FIELDS = ['summary', 'status', 'priority', 'assignee', 'created', 'resolutiondate', 'issuetype'];

const TZ_OFFSET_MS = -5 * 60 * 60 * 1000; // America/Bogota, sin horario de verano

function weekStart(dateMs) {
  const d = new Date(dateMs + TZ_OFFSET_MS);
  const day = (d.getUTCDay() + 6) % 7; // lunes = 0
  d.setUTCDate(d.getUTCDate() - day);
  return d.toISOString().slice(0, 10);
}

function round(n, digits = 1) {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function countBy(items, keyFn) {
  const out = {};
  for (const item of items) {
    const k = keyFn(item) || 'Sin dato';
    out[k] = (out[k] || 0) + 1;
  }
  return out;
}

/** Consulta Jira y devuelve los datos crudos mínimos de la ventana pedida. */
export async function fetchMesaIssues(site, projectKey, days) {
  const jql = `project = "${projectKey}" AND created >= -${days}d ORDER BY created DESC`;
  const raw = await searchIssues(site, jql, MESAS_FIELDS);
  return raw.map((i) => ({
    key: i.key,
    resumen: i.fields.summary,
    estado: i.fields.status?.name,
    categoriaEstado: i.fields.status?.statusCategory?.key, // new | indeterminate | done
    prioridad: i.fields.priority?.name,
    tipo: i.fields.issuetype?.name,
    asignado: i.fields.assignee?.displayName || null,
    creado: i.fields.created,
    resuelto: i.fields.resolutiondate || null,
  }));
}

/** Calcula el resumen del tablero. `includeAssignee=false` para el rol cliente. */
export function buildMesaSummary(issues, { site, projectKey, days, siteUrl, includeAssignee }) {
  const abiertos = issues.filter((i) => i.categoriaEstado !== 'done');
  const resueltos = issues.filter((i) => i.categoriaEstado === 'done');

  const horas = resueltos
    .filter((i) => i.resuelto)
    .map((i) => (Date.parse(i.resuelto) - Date.parse(i.creado)) / 36e5)
    .filter((h) => Number.isFinite(h) && h >= 0);

  const semanas = {};
  for (const i of issues) {
    const w = weekStart(Date.parse(i.creado));
    semanas[w] ??= { semana: w, creados: 0, resueltos: 0 };
    semanas[w].creados += 1;
  }
  for (const i of resueltos) {
    if (!i.resuelto) continue;
    const w = weekStart(Date.parse(i.resuelto));
    semanas[w] ??= { semana: w, creados: 0, resueltos: 0 };
    semanas[w].resueltos += 1;
  }

  const abiertosLista = abiertos.slice(0, 200).map((i) => ({
    key: i.key,
    resumen: i.resumen,
    estado: i.estado,
    prioridad: i.prioridad,
    creado: i.creado,
    ...(includeAssignee ? { asignado: i.asignado } : {}),
    url: `${siteUrl}/browse/${i.key}`,
  }));

  return {
    proyecto: `${site}:${projectKey}`,
    ventanaDias: days,
    totales: {
      solicitudes: issues.length,
      abiertas: abiertos.length,
      resueltas: resueltos.length,
      tasaResolucion: issues.length ? round((resueltos.length / issues.length) * 100) : null,
    },
    resolucionHoras: {
      promedio: horas.length ? round(horas.reduce((a, b) => a + b, 0) / horas.length) : null,
      mediana: horas.length ? round(median(horas)) : null,
    },
    porEstado: countBy(issues, (i) => i.estado),
    porPrioridad: countBy(issues, (i) => i.prioridad),
    abiertasPorAsignado: includeAssignee ? countBy(abiertos, (i) => i.asignado || 'Sin asignar') : undefined,
    porSemana: Object.values(semanas).sort((a, b) => a.semana.localeCompare(b.semana)),
    abiertas: abiertosLista,
    truncado: issues.length >= 2000,
  };
}
