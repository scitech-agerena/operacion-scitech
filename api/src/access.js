/**
 * Control de acceso. Todo lo que no esté explícitamente permitido se deniega.
 * La identidad (correo) la entrega oauth2-proxy a través de Caddy; la API
 * nunca es accesible directamente desde Internet.
 */

export function resolveUser(email, access) {
  if (!email) return null;
  const entry = access.users[email.toLowerCase()];
  if (!entry) return null;
  const role = access.roles[entry.role];
  if (!role) return null;
  return {
    email: email.toLowerCase(),
    role: entry.role,
    dashboards: role.dashboards || [],
    projects: entry.projects || [],
  };
}

export function canSeeDashboard(user, dashboard) {
  return user.dashboards.includes('*') || user.dashboards.includes(dashboard);
}

export function canSeeProject(user, projectId) {
  return user.projects.includes('*') || user.projects.includes(projectId);
}
