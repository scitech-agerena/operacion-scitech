import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../src/config.js';
import { createServer } from '../src/server.js';
import { startMockJira } from './mock-jira.js';

/**
 * Ambiente local de desarrollo.
 *   npm run dev       → Jira simulado (sin credenciales)
 *   npm run dev:real  → Jira real de solo lectura, con credenciales en api/.env.dev
 *
 * Reemplaza a Caddy + oauth2-proxy: sirve los tableros, reenvía /api a la API
 * e inyecta el correo del "usuario de prueba" elegido en /_dev.
 * Escucha solo en 127.0.0.1 para que nadie en la red pueda suplantar usuarios.
 */

const here = path.dirname(fileURLToPath(import.meta.url));
const apiDir = path.join(here, '..');
const root = path.join(apiDir, '..');
const real = process.argv.includes('--real');

const HOST = '127.0.0.1';
const WEB_PORT = Number(process.env.WEB_PORT) || 8080;
const API_PORT = Number(process.env.API_PORT) || 3000;
const MOCK_PORT = Number(process.env.MOCK_PORT) || 4010;

const MIME = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
};

function parseEnvFile(file) {
  const out = {};
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && !line.trim().startsWith('#')) out[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
  return out;
}

function fail(msg) {
  console.error(`\n✗ ${msg}\n`);
  process.exit(1);
}

// ---------- Configuración según el modo ----------
let env = { ...process.env, PORT: String(API_PORT) };

if (real) {
  const envFile = path.join(apiDir, '.env.dev');
  if (!fs.existsSync(envFile)) fail('Falta api/.env.dev. Cópialo desde api/.env.dev.example y completa las credenciales de Jira.');
  if (!fs.existsSync(path.join(apiDir, 'config', 'access.json')) || !fs.existsSync(path.join(apiDir, 'config', 'projects.json'))) {
    fail('Faltan api/config/access.json y api/config/projects.json. Cópialos desde los archivos .example.json y ajústalos a tus proyectos.');
  }
  env = { ...env, ...parseEnvFile(envFile), CONFIG_DIR: path.join(apiDir, 'config') };
} else {
  await startMockJira(MOCK_PORT).catch((e) => fail(`No se pudo iniciar el Jira simulado en el puerto ${MOCK_PORT}: ${e.message}`));
  env = {
    ...env,
    JIRA_DEMO_URL: `http://${HOST}:${MOCK_PORT}`,
    JIRA_DEMO_EMAIL: 'demo@demo.local',
    JIRA_DEMO_TOKEN: 'demo',
    CONFIG_DIR: path.join(here, 'config'),
    CACHE_TTL_SECONDS: env.CACHE_TTL_SECONDS || '30',
  };
}

const config = loadConfig(env);
const users = Object.keys(config.access.users);
if (!users.length) fail('access.json no tiene usuarios.');

await new Promise((resolve, reject) => {
  const api = createServer(config);
  api.once('error', reject);
  api.listen(API_PORT, HOST, resolve);
}).catch((e) => fail(`No se pudo iniciar la API en el puerto ${API_PORT}: ${e.message}`));

// ---------- Servidor web de desarrollo ----------
function currentUser(req) {
  const cookie = /(?:^|;\s*)dev_user=([^;]+)/.exec(req.headers.cookie || '')?.[1];
  const email = cookie ? decodeURIComponent(cookie) : '';
  return users.includes(email) ? email : users[0];
}

function banner(email) {
  const safe = email.replace(/[<>&"]/g, '');
  return `<div style="position:fixed;bottom:0;left:0;right:0;background:#1d2433;color:#fff;font:13px system-ui;padding:6px 12px;text-align:center;z-index:9999">` +
    `DESARROLLO (${real ? 'Jira real' : 'Jira simulado'}) · usuario: <b>${safe}</b> · <a href="/_dev" style="color:#9cc2ff">cambiar usuario</a></div>`;
}

function serveStatic(req, res, pathname) {
  let base = path.join(root, 'tableros');
  let rel = pathname;
  if (pathname.startsWith('/shared/')) {
    base = path.join(root, 'shared');
    rel = pathname.slice('/shared'.length);
  }
  let file = path.join(base, decodeURIComponent(rel));
  if (file !== base && !file.startsWith(base + path.sep)) { res.writeHead(403); return res.end('Prohibido'); }
  if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
  if (!fs.existsSync(file)) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); return res.end('No encontrado'); }

  const type = MIME[path.extname(file)] || 'application/octet-stream';
  let body = fs.readFileSync(file);
  if (type.startsWith('text/html')) body = Buffer.from(body.toString('utf8').replace('</body>', `${banner(currentUser(req))}</body>`));
  res.writeHead(200, { 'Content-Type': type, 'Cache-Control': 'no-store' });
  res.end(body);
}

http.createServer((req, res) => {
  const url = new URL(req.url, `http://${HOST}`);

  if (url.pathname === '/_dev') {
    const me = currentUser(req);
    const items = users.map((u) => {
      const entry = config.access.users[u];
      return `<li style="margin:8px 0"><a href="/_dev/as?email=${encodeURIComponent(u)}">${u.replace(/[<>&"]/g, '')}</a> · rol: ${entry.role}${u === me ? ' <b>(actual)</b>' : ''}</li>`;
    }).join('');
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(`<!doctype html><meta charset="utf-8"><title>Usuario de prueba</title><body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 16px"><h1>Usuario de prueba</h1><p>Elige con qué correo entras a los tableros.</p><ul>${items}</ul><p><a href="/">Ir a los tableros</a></p></body>`);
  }

  if (url.pathname === '/_dev/as') {
    const email = url.searchParams.get('email') || '';
    if (users.includes(email)) res.setHeader('Set-Cookie', `dev_user=${encodeURIComponent(email)}; Path=/; SameSite=Strict`);
    res.writeHead(302, { Location: '/' });
    return res.end();
  }

  if (url.pathname.startsWith('/api/')) {
    const headers = { ...req.headers, host: `${HOST}:${API_PORT}`, 'x-auth-request-email': currentUser(req) };
    delete headers.cookie;
    const proxy = http.request({ host: HOST, port: API_PORT, path: req.url, method: req.method, headers }, (up) => {
      res.writeHead(up.statusCode, up.headers);
      up.pipe(res);
    });
    proxy.on('error', () => { res.writeHead(502); res.end('API no disponible'); });
    return req.pipe(proxy);
  }

  serveStatic(req, res, url.pathname);
}).listen(WEB_PORT, HOST, () => {
  console.log(`\n  Ambiente local (${real ? 'Jira REAL, solo lectura' : 'Jira SIMULADO'})`);
  console.log(`  Tableros:         http://localhost:${WEB_PORT}`);
  console.log(`  Cambiar usuario:  http://localhost:${WEB_PORT}/_dev`);
  console.log(`  Usuarios:         ${users.join(', ')}`);
  console.log(`  Sitios Jira:      ${Object.keys(config.sites).join(', ') || 'ninguno'}\n`);
}).on('error', (e) => fail(`No se pudo abrir el puerto ${WEB_PORT}: ${e.message} (puedes usar WEB_PORT=otro)`));
