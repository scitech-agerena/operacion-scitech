import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    console.error(`[config] No se pudo leer ${file}: ${err.message}`);
    return fallback;
  }
}

/**
 * Carga la configuración desde variables de entorno y archivos JSON.
 * Falla cerrado: si falta access.json nadie tiene acceso.
 */
export function loadConfig(env = process.env) {
  const configDir = env.CONFIG_DIR || path.join(here, '..', 'config');

  // Sitios Jira: cualquier variable JIRA_<SITIO>_URL con su _EMAIL y _TOKEN
  const sites = {};
  for (const key of Object.keys(env)) {
    const m = key.match(/^JIRA_([A-Z0-9]+)_URL$/);
    if (!m) continue;
    const name = m[1].toLowerCase();
    const email = env[`JIRA_${m[1]}_EMAIL`];
    const token = env[`JIRA_${m[1]}_TOKEN`];
    if (env[key] && email && token) {
      sites[name] = { url: env[key].replace(/\/+$/, ''), email, token };
    } else {
      console.error(`[config] Sitio Jira "${name}" incompleto: faltan URL, EMAIL o TOKEN`);
    }
  }

  const rawAccess = readJson(path.join(configDir, 'access.json'), { roles: {}, users: {} });
  const users = {};
  for (const [email, value] of Object.entries(rawAccess.users || {})) {
    users[email.toLowerCase()] = value;
  }
  const access = { roles: rawAccess.roles || {}, users };

  const projects = readJson(path.join(configDir, 'projects.json'), { projects: [] }).projects || [];

  return {
    port: Number(env.PORT) || 3000,
    cacheTtlMs: (Number(env.CACHE_TTL_SECONDS) || 600) * 1000,
    sites,
    access,
    projects,
  };
}
