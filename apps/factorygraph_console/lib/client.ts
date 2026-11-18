export class APIError extends Error {
  constructor(
    public status: number,
    public code: string,
    public requestId?: string,
  ) {
    super(code);
  }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, cache: "no-store", credentials: "same-origin" });
  const value = await response.json().catch(() => ({ error: "invalid_response" }));
  if (!response.ok)
    throw new APIError(response.status, value.error ?? "request_unavailable", value.request_id);
  return value as T;
}
// One queue per authenticated console instance. No shared browser/global data cache.
export function queue() {
  let tail = Promise.resolve();
  return <T>(operation: () => Promise<T>): Promise<T> => {
    const result = tail.then(operation, operation);
    tail = result.then(
      () => {},
      () => {},
    );
    return result;
  };
}
export function query(resource: string, params: Record<string, string | number>) {
  return `/api/data/${resource}?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))}`;
}
