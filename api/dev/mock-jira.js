import http from 'node:http';

/**
 * Jira simulado para desarrollo local. Responde la misma búsqueda que usa la API
 * (POST /rest/api/3/search/jql) con solicitudes generadas de forma determinista.
 */

const STATUSES = [
  { name: 'Abierta', cat: 'new' },
  { name: 'En curso', cat: 'indeterminate' },
  { name: 'En revisión', cat: 'indeterminate' },
  { name: 'Resuelta', cat: 'done' },
  { name: 'Cerrada', cat: 'done' },
];
const PRIORITIES = ['Crítica', 'Alta', 'Media', 'Baja'];
const PEOPLE = ['Ana Demo', 'Luis Demo', 'Marta Demo', 'Carlos Demo', null];
const TYPES = ['Incidente', 'Solicitud', 'Consulta'];
const TITLES = [
  'No carga el módulo de reportes',
  'Error al guardar el formulario',
  'Solicitud de nuevo usuario',
  'Consulta sobre permisos',
  'Lentitud en la consulta de facturas',
  'Ajuste en el informe mensual',
  'Falla de inicio de sesión',
  'Cambio de datos maestros',
];

function seeded(seed) {
  let s = [...seed].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function generate(projectKey, now) {
  const rand = seeded(projectKey);
  const total = 160;
  const issues = [];
  for (let n = 1; n <= total; n++) {
    const daysAgo = Math.floor(rand() ** 1.4 * 150);
    const created = now - daysAgo * 864e5 - Math.floor(rand() * 864e5);
    const priority = PRIORITIES[Math.floor(rand() * rand() * PRIORITIES.length)];
    const wantsDone = rand() < Math.min(0.92, 0.35 + daysAgo / 120);
    let status = STATUSES[Math.floor(rand() * 3)];
    let resolved = null;
    if (wantsDone) {
      const hours = 4 + Math.floor(rand() * rand() * 140);
      const at = created + hours * 36e5;
      if (at < now) {
        status = STATUSES[3 + Math.floor(rand() * 2)];
        resolved = new Date(at).toISOString();
      }
    }
    issues.push({
      key: `${projectKey}-${n}`,
      createdMs: created,
      fields: {
        summary: TITLES[Math.floor(rand() * TITLES.length)],
        status: { name: status.name, statusCategory: { key: status.cat } },
        priority: { name: priority },
        assignee: (() => { const p = PEOPLE[Math.floor(rand() * PEOPLE.length)]; return p ? { displayName: p } : null; })(),
        created: new Date(created).toISOString(),
        resolutiondate: resolved,
        issuetype: { name: TYPES[Math.floor(rand() * TYPES.length)] },
      },
    });
  }
  return issues.sort((a, b) => b.createdMs - a.createdMs);
}

export function startMockJira(port) {
  const now = Date.now();
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://mock');

    // Página mínima para los enlaces /browse/CLAVE del tablero
    if (req.method === 'GET' && url.pathname.startsWith('/browse/')) {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(`<!doctype html><meta charset="utf-8"><title>Jira simulado</title><p style="font-family:sans-serif;padding:24px">Jira simulado · ${url.pathname.slice(8).replace(/[^A-Za-z0-9_-]/g, '')}</p>`);
      return;
    }

    if (req.method === 'POST' && url.pathname === '/rest/api/3/search/jql') {
      let body = '';
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        let q;
        try { q = JSON.parse(body || '{}'); } catch { q = {}; }
        const key = /project\s*=\s*"([A-Z0-9_]+)"/.exec(q.jql || '')?.[1];
        const days = Number(/created\s*>=\s*-(\d+)d/.exec(q.jql || '')?.[1]) || 90;
        if (!key) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          return res.end(JSON.stringify({ errorMessages: ['JQL no soportado por el Jira simulado'] }));
        }
        const all = generate(key, now).filter((i) => i.createdMs >= now - days * 864e5);
        const size = Math.min(Number(q.maxResults) || 100, 100);
        const offset = Number(q.nextPageToken) || 0;
        const page = all.slice(offset, offset + size).map(({ key: k, fields }) => ({ key: k, fields }));
        const end = offset + size;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ issues: page, isLast: end >= all.length, nextPageToken: end < all.length ? String(end) : undefined }));
      });
      return;
    }

    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ errorMessages: ['No encontrado'] }));
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}
