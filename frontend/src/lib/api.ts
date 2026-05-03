const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export class ApiError extends Error {
  status: number;
  detail: Record<string, unknown>;

  constructor(message: string, status: number, detail: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const defaultHeaders: Record<string, string> = isFormData ? {} : { 'Content-Type': 'application/json' };
  const { headers: optHeaders, ...restOptions } = options || {};
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: {
      ...defaultHeaders,
      ...(optHeaders as Record<string, string>),
    },
    ...restOptions,
  });

  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      window.location.href = '/login';
    }
    throw new ApiError('Unauthorized', 401);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ message: res.statusText }));
    // FastAPI validation errors come as { detail: { error, blocks, hint } }
    // Generic errors come as { detail: "string" } or { message: "string" }
    const detail = typeof body.detail === 'object' && body.detail !== null ? body.detail : {};
    const message =
      (typeof body.detail === 'string' ? body.detail : null) ||
      body.message ||
      body.error?.message ||
      `HTTP ${res.status}`;
    throw new ApiError(message, res.status, detail);
  }

  return res.json();
}

// Convenience methods
export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
};
