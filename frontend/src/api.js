const API = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

export const apiUrl = (path) => `${API}${path}`;

export async function api(path, opts = {}) {
  const res = await fetch(apiUrl(path), {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    let body = '';
    try {
      body = (await res.json()).error || '';
    } catch {
      body = await res.text().catch(() => '');
    }
    throw new Error(body || `${res.status} ${res.statusText}`);
  }
  return res.json();
}
