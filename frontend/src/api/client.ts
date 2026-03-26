export const API_BASE = import.meta.env.DEV ? '/api' : '';
const DEFAULT_SCOPE = (import.meta.env.VITE_KNOWLEDGE_SCOPE || 'audit').trim().toLowerCase();

export function getCurrentKnowledgeScope(): string {
  if (typeof window === 'undefined') {
    return DEFAULT_SCOPE;
  }
  const localValue = String(window.localStorage.getItem('rag.scope') || '').trim().toLowerCase();
  return localValue || DEFAULT_SCOPE;
}

export function resolveApiUrl(pathOrUrl: string): string {
  const raw = String(pathOrUrl || '').trim();
  if (!raw) return '';
  if (/^https?:\/\//i.test(raw)) return raw;
  if (raw.startsWith('/')) {
    return `${API_BASE}${raw}`;
  }
  return `${API_BASE}/${raw}`;
}

export function buildScopedHeaders(initHeaders?: HeadersInit): Headers {
  const headers = new Headers(initHeaders || {});
  if (!headers.has('X-Knowledge-Scope')) {
    headers.set('X-Knowledge-Scope', getCurrentKnowledgeScope());
  }
  return headers;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...(init || {}),
    headers: buildScopedHeaders(init?.headers),
  });

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(`接口返回非 JSON: ${text.slice(0, 120)}`);
    }
  }

  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload !== null && 'error' in payload
        ? String((payload as { error: unknown }).error)
        : `请求失败 (${response.status})`;
    throw new Error(message);
  }

  return payload as T;
}
