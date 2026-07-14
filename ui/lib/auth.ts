// API key helpers for self-hosted install (no login accounts).

const API_BASE =
  process.env.NEXT_PUBLIC_ROUTISM_API ?? "http://localhost:8000";

const KEY_STORAGE = "routism_api_key";

export type ApiKeyMeta = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: number;
  last_used_at: number | null;
  revoked: boolean;
};

export type KeysList = {
  keys: ApiKeyMeta[];
  base_url: string;
  model: string;
};

export type CreateKeyResult = {
  key: ApiKeyMeta;
  secret: string;
  message: string;
};

export function getApiBase(): string {
  return API_BASE;
}

export function getStoredApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(KEY_STORAGE);
}

export function setStoredApiKey(key: string | null): void {
  if (typeof window === "undefined") return;
  if (key) localStorage.setItem(KEY_STORAGE, key);
  else localStorage.removeItem(KEY_STORAGE);
}

export function authHeaders(extra?: HeadersInit): HeadersInit {
  const key = getStoredApiKey();
  const h: Record<string, string> = {
    "content-type": "application/json",
  };
  if (key) h["Authorization"] = `Bearer ${key}`;
  if (extra) Object.assign(h, extra as Record<string, string>);
  return h;
}

async function afetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  let body: unknown = null;
  const text = await r.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!r.ok) {
    let msg = `${r.status}`;
    if (body && typeof body === "object" && "detail" in (body as object)) {
      const d = (body as { detail: unknown }).detail;
      msg = typeof d === "string" ? d : JSON.stringify(d);
    } else if (typeof body === "string") {
      msg = body;
    }
    throw new Error(msg);
  }
  return body as T;
}

export async function listKeys(): Promise<KeysList> {
  return afetch<KeysList>("/v1/keys");
}

export async function createKey(name: string): Promise<CreateKeyResult> {
  const res = await afetch<CreateKeyResult>("/v1/keys", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  // Prefer newest secret as stored agent key if none yet
  if (res.secret && !getStoredApiKey()) {
    setStoredApiKey(res.secret);
  }
  return res;
}

export async function revokeKey(keyId: string): Promise<void> {
  await afetch(`/v1/keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
  });
}
