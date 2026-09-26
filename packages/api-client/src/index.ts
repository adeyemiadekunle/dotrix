// Typed client for the pmagent API (apps/backend). Web and desktop both use this.
// Replace with a client generated from the backend's OpenAPI schema once routes exist.

export interface ClientOptions {
  baseUrl: string;
  token?: string;
}

export function createClient({ baseUrl, token }: ClientOptions) {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
    if (!res.ok) throw new Error(`${init.method ?? "GET"} ${path} failed: ${res.status}`);
    return (await res.json()) as T;
  }

  return {
    health: () => request<{ status: string }>("/health"),
  };
}

export type PmagentClient = ReturnType<typeof createClient>;
