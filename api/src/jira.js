const PROJECT_KEY = /^[A-Z][A-Z0-9_]{1,19}$/;

export function isValidProjectKey(key) {
  return PROJECT_KEY.test(key);
}

/**
 * Consulta de solo lectura a Jira Cloud (API v3, búsqueda por JQL con paginación por token).
 * Las credenciales salen únicamente de la configuración del servidor.
 */
export async function searchIssues(site, jql, fields, { cap = 2000, pageSize = 100 } = {}) {
  const auth = 'Basic ' + Buffer.from(`${site.email}:${site.token}`).toString('base64');
  const issues = [];
  let nextPageToken;

  while (issues.length < cap) {
    const body = { jql, fields, maxResults: pageSize };
    if (nextPageToken) body.nextPageToken = nextPageToken;

    const res = await fetch(`${site.url}/rest/api/3/search/jql`, {
      method: 'POST',
      headers: { Authorization: auth, Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
    });

    if (!res.ok) {
      throw new Error(`Jira respondió ${res.status} ${res.statusText}`);
    }

    const data = await res.json();
    issues.push(...(data.issues || []));
    if (data.isLast || !data.nextPageToken) break;
    nextPageToken = data.nextPageToken;
  }

  return issues.slice(0, cap);
}
