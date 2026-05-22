// Part Finder API client — talks to /api/part-finder.
// Anonymous by default; if an OPENDC auth token is present it's sent, which
// unlocks full (paid) results server-side.

const BASE = (import.meta.env.VITE_API_URL || '') + '/api/part-finder';

function authHeaders() {
  const t = localStorage.getItem('authToken');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function get(path, params) {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await fetch(BASE + path + qs, { headers: { ...authHeaders() } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.detail?.detail || body.detail || res.statusText);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return res.json();
}

export const partFinder = {
  stats: () => get('/stats'),
  facets: () => get('/facets'),
  brands: (params) => get('/brands', params),
  documents: (params) => get('/documents', params),
  document: (id) => get(`/documents/${id}`),
  search: (q, category) => get('/search', category ? { q, category } : { q }),
  partNumber: (token) => get(`/part-number/${encodeURIComponent(token)}`),
  coverUrl: (id) => `${BASE}/cover/${id}`,
  pdfUrl: (id) => `${BASE}/pdf/${id}`,

  async identify({ file, category, note }) {
    const fd = new FormData();
    fd.append('image', file);
    if (category) fd.append('category', category);
    if (note) fd.append('note', note);
    const res = await fetch(BASE + '/identify', {
      method: 'POST',
      headers: { ...authHeaders() },
      body: fd,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(body.detail?.detail || body.detail || res.statusText);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  },
};

export function isAuthed() {
  return !!localStorage.getItem('authToken');
}
