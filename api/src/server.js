import http from 'node:http';
import { pathToFileURL } from 'node:url';
import { loadConfig } from './config.js';
import { resolveUser, canSeeDashboard, canSeeProject } from './access.js';
import { createCache } from './cache.js';
import { isValidProjectKey } from './jira.js';
import { fetchMesaIssues, buildMesaSummary } from './mesas.js';

const MAX_DAYS = 365;
const DEFAULT_DAYS = 90;

function send(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end(payload);
}

export function createServer(config) {
  const cached = createCache(config.cacheTtlMs);

  return http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://internal');
    const email = req.headers['x-auth-request-email'];
    const user = resolveUser(email, config.access);
    const started = Date.now();

    // Registro de accesos (auditoría). Nunca se registran tokens.
    res.on('finish', () => {
      console.log(JSON.stringify({
        t: new Date().toISOString(),
        user: user?.email || email || null,
        path: url.pathname,
        project: url.searchParams.get('project') || undefined,
        status: res.statusCode,
        ms: Date.now() - started,
      }));
    });

    try {
      if (req.method !== 'GET') return send(res, 405, { error: 'Método no permitido' });

      if (!user) return send(res, 403, { error: 'Sin acceso' });

      if (url.pathname === '/api/me') {
        const projects = config.projects
          .filter((p) => canSeeProject(user, `${p.site}:${p.key}`))
          .map((p) => ({ id: `${p.site}:${p.key}`, nombre: p.name, tipo: p.type }));
        return send(res, 200, { email: user.email, rol: user.role, dashboards: user.dashboards, proyectos: projects });
      }

      // Lo consulta Caddy (forward_auth) antes de entregar un tablero generado: 204 = permitido, 403 = denegado.
      const authz = url.pathname.match(/^\/api\/authz\/([a-z0-9-]{1,40})$/);
      if (authz) {
        return canSeeDashboard(user, authz[1]) ? (res.writeHead(204), res.end()) : send(res, 403, { error: 'Sin acceso' });
      }

      if (url.pathname === '/api/mesas') {
        if (!canSeeDashboard(user, 'mesas-servicio')) return send(res, 403, { error: 'Sin acceso' });

        const projectId = url.searchParams.get('project') || '';
        const [siteName, projectKey] = projectId.split(':');
        const days = Math.min(Math.max(parseInt(url.searchParams.get('days'), 10) || DEFAULT_DAYS, 1), MAX_DAYS);

        if (!siteName || !isValidProjectKey(projectKey || '')) {
          return send(res, 400, { error: 'Parámetro project inválido (formato sitio:CLAVE)' });
        }

        // El proyecto debe estar en la lista blanca Y el usuario debe tener permiso sobre él.
        const listed = config.projects.some((p) => p.site === siteName && p.key === projectKey);
        const site = config.sites[siteName];
        if (!listed || !site || !canSeeProject(user, projectId)) {
          return send(res, 403, { error: 'Sin acceso' });
        }

        const { value: issues, cachedAt } = await cached(`mesas:${projectId}:${days}`, () =>
          fetchMesaIssues(site, projectKey, days),
        );

        const summary = buildMesaSummary(issues, {
          site: siteName,
          projectKey,
          days,
          siteUrl: site.url,
          includeAssignee: user.role !== 'cliente',
        });

        return send(res, 200, { ...summary, actualizado: new Date(cachedAt).toISOString() });
      }

      return send(res, 404, { error: 'No encontrado' });
    } catch (err) {
      console.error(`[error] ${url.pathname}: ${err.message}`);
      return send(res, 502, { error: 'No se pudo obtener la información de Jira' });
    }
  });
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const config = loadConfig();
  createServer(config).listen(config.port, () => {
    console.log(`[api] escuchando en :${config.port} · sitios Jira: ${Object.keys(config.sites).join(', ') || 'ninguno'}`);
  });
}
