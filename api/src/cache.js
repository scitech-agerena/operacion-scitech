/**
 * Caché en memoria con TTL y deduplicación de consultas en curso:
 * si varias personas piden lo mismo a la vez, Jira recibe una sola consulta.
 */
export function createCache(ttlMs) {
  const store = new Map();
  const inflight = new Map();

  return async function cached(key, loader) {
    const hit = store.get(key);
    if (hit && hit.expires > Date.now()) return { value: hit.value, cachedAt: hit.cachedAt, fromCache: true };

    if (inflight.has(key)) return inflight.get(key);

    const promise = (async () => {
      try {
        const value = await loader();
        const cachedAt = Date.now();
        store.set(key, { value, cachedAt, expires: cachedAt + ttlMs });
        return { value, cachedAt, fromCache: false };
      } finally {
        inflight.delete(key);
      }
    })();

    inflight.set(key, promise);
    return promise;
  };
}
