export const API_BASE = import.meta.env.DEV ? '/api' : '';

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);

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
