import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createServer } from '../src/server.js';

let jira, api, base;
let jiraCalls = 0;
let lastJql = '';
let lastAuth = '';

const issues = [
  { key: 'EJ-1', fields: { summary: 'Falla A', status: { name: 'Abierta', statusCategory: { key: 'new' } }, priority: { name: 'Alta' }, assignee: { displayName: 'Ana' }, created: '2026-10-05T15:00:00.000-0500', resolutiondate: null, issuetype: { name: 'Incidente' } } },
  { key: 'EJ-2', fields: { summary: 'Falla B', status: { name: 'En curso', statusCategory: { key: 'indeterminate' } }, priority: { name: 'Media' }, assignee: null, created: '2026-10-06T09:00:00.000-0500', resolutiondate: null, issuetype: { name: 'Incidente' } } },
  { key: 'EJ-3', fields: { summary: 'Falla C', status: { name: 'Resuelta', statusCategory: { key: 'done' } }, priority: { name: 'Alta' }, assignee: { displayName: 'Luis' }, created: '2026-10-01T10:00:00.000-0500', resolutiondate: '2026-10-02T10:00:00.000-0500', issuetype: { name: 'Incidente' } } },
];

before(async () => {
  jira = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      jiraCalls += 1;
      lastAuth = req.headers.authorization || '';
      lastJql = JSON.parse(body || '{}').jql || '';
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ issues, isLast: true }));
    });
  });
  await new Promise((r) => jira.listen(0, r));

  const config = {
    port: 0,
    cacheTtlMs: 60000,
    sites: { scitech: { url: `http://127.0.0.1:${jira.address().port}`, email: 'svc@scitech.com.co', token: 'tok' } },
    projects: [{ site: 'scitech', key: 'EJEMPLO1', name: 'Mesa ejemplo', type: 'mesa-servicio' },
               { site: 'scitech', key: 'EJEMPLO2', name: 'Otra mesa', type: 'mesa-servicio' }],
    access: {
      roles: { comite: { dashboards: ['*'] }, cliente: { dashboards: ['mesas-servicio'] }, otro: { dashboards: ['otro'] } },
      users: {
        'comite@scitech.com.co': { role: 'comite', projects: ['*'] },
        'cli@externo.com': { role: 'cliente', projects: ['scitech:EJEMPLO1'] },
        'sin@scitech.com.co': { role: 'otro', projects: ['*'] },
      },
    },
  };
  api = createServer(config);
  await new Promise((r) => api.listen(0, r));
  base = `http://127.0.0.1:${api.address().port}`;
});

after(() => {
  api.close();
  jira.close();
});

const get = (path, email) => fetch(base + path, { headers: email ? { 'X-Auth-Request-Email': email } : {} });

test('sin identidad: 403', async () => {
  assert.equal((await get('/api/me')).status, 403);
});

test('usuario no registrado: 403', async () => {
  assert.equal((await get('/api/me', 'intruso@gmail.com')).status, 403);
});

test('/api/me lista solo los proyectos permitidos', async () => {
  const body = await (await get('/api/me', 'cli@externo.com')).json();
  assert.deepEqual(body.proyectos.map((p) => p.id), ['scitech:EJEMPLO1']);
});

test('comité obtiene resumen correcto con responsables', async () => {
  const res = await get('/api/mesas?project=scitech:EJEMPLO1&days=90', 'Comite@scitech.com.co');
  assert.equal(res.status, 200);
  const d = await res.json();
  assert.deepEqual(d.totales, { solicitudes: 3, abiertas: 2, resueltas: 1, tasaResolucion: 33.3 });
  assert.equal(d.resolucionHoras.mediana, 24);
  assert.equal(d.porEstado.Abierta, 1);
  assert.equal(d.abiertasPorAsignado.Ana, 1);
  assert.equal(d.abiertasPorAsignado['Sin asignar'], 1);
  assert.ok(d.abiertas[0].url.endsWith('/browse/EJ-1'));
  assert.match(lastJql, /project = "EJEMPLO1"/);
  assert.match(lastAuth, /^Basic /);
});

test('cliente no recibe nombres de responsables', async () => {
  const d = await (await get('/api/mesas?project=scitech:EJEMPLO1', 'cli@externo.com')).json();
  assert.equal(d.abiertasPorAsignado, undefined);
  assert.ok(d.abiertas.every((i) => !('asignado' in i)));
});

test('cliente no puede ver un proyecto que no tiene asignado', async () => {
  assert.equal((await get('/api/mesas?project=scitech:EJEMPLO2', 'cli@externo.com')).status, 403);
});

test('rol sin acceso al tablero: 403', async () => {
  assert.equal((await get('/api/mesas?project=scitech:EJEMPLO1', 'sin@scitech.com.co')).status, 403);
});

test('proyecto fuera de la lista blanca: 403', async () => {
  assert.equal((await get('/api/mesas?project=scitech:OTRO', 'comite@scitech.com.co')).status, 403);
});

test('clave con intento de inyección JQL: 400 y sin consulta a Jira', async () => {
  const before = jiraCalls;
  const bad = encodeURIComponent('scitech:X" OR project is not EMPTY OR "1');
  assert.equal((await get(`/api/mesas?project=${bad}`, 'comite@scitech.com.co')).status, 400);
  assert.equal(jiraCalls, before);
});

test('la caché evita consultas repetidas a Jira', async () => {
  await get('/api/mesas?project=scitech:EJEMPLO1&days=30', 'comite@scitech.com.co');
  const after1 = jiraCalls;
  await get('/api/mesas?project=scitech:EJEMPLO1&days=30', 'cli@externo.com');
  await get('/api/mesas?project=scitech:EJEMPLO1&days=30', 'comite@scitech.com.co');
  assert.equal(jiraCalls, after1);
});

test('método distinto de GET: 405', async () => {
  const res = await fetch(base + '/api/me', { method: 'POST', headers: { 'X-Auth-Request-Email': 'comite@scitech.com.co' } });
  assert.equal(res.status, 405);
});

test('authz por tablero: comité 204, cliente y rol ajeno 403, sin identidad 403', async () => {
  assert.equal((await get('/api/authz/mesas-interna', 'comite@scitech.com.co')).status, 204);
  assert.equal((await get('/api/authz/mesas-interna', 'cli@externo.com')).status, 403);
  assert.equal((await get('/api/authz/mesas-servicio', 'cli@externo.com')).status, 204);
  assert.equal((await get('/api/authz/colaboradores', 'sin@scitech.com.co')).status, 403);
  assert.equal((await get('/api/authz/mesas-interna')).status, 403);
});

test('authz: identificador inválido no llega a la comprobación (404)', async () => {
  assert.equal((await get('/api/authz/..%2Fme', 'comite@scitech.com.co')).status, 404);
  assert.equal((await get('/api/authz/MESAS', 'comite@scitech.com.co')).status, 404);
});
