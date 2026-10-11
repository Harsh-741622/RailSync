const API_ROOT = import.meta.env.VITE_API_ROOT || (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api');
const API_TOKEN = import.meta.env.VITE_RAILSYNC_AUTH_TOKEN;

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}), ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return body as T;
}

export const post = <T = any>(path: string, data?: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(data ?? {}) });
export const patch = <T = any>(path: string, data?: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(data ?? {}) });
export const del = <T = any>(path: string) => api<T>(path, { method: 'DELETE' });

export async function postAudio(path: string, data: unknown): Promise<Blob> {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}) },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
  }
  return response.blob();
}
