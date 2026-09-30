import { exports } from "cloudflare:workers";

export const ADMIN = "test-admin-secret";

export function call(path: string, init: RequestInit & { token?: string } = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.token !== undefined) headers.set("Authorization", `Bearer ${init.token}`);
  return exports.default.fetch(new Request(`https://pool.test${path}`, { ...init, headers }));
}

export async function addKey(name: string): Promise<string> {
  const res = await call("/keys", { method: "POST", token: ADMIN, body: JSON.stringify({ name }) });
  if (res.status !== 201) throw new Error(`addKey ${name}: ${res.status}`);
  const body = (await res.json()) as { key: string };
  return body.key;
}

export type Header = { era: string; realm: string; faction: string; requestedAt: string };

export function header(overrides: Partial<Header> = {}): Header {
  return { era: "live", realm: "Forever", faction: "Horde", requestedAt: "1790000000", ...overrides };
}

export async function gzip(text: string): Promise<Uint8Array> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function scanBody(h: Header = header()): Promise<Uint8Array> {
  return gzip(JSON.stringify({ era: h.era, scan: { realm: h.realm, faction: h.faction, requestedAt: Number(h.requestedAt) } }));
}

export function upload(token: string, h: Header, body: BodyInit): Promise<Response> {
  return call("/scans", {
    method: "POST",
    token,
    body,
    headers: {
      "Content-Type": "application/gzip",
      "X-Scan-Era": h.era,
      "X-Scan-Realm": h.realm,
      "X-Scan-Faction": h.faction,
      "X-Scan-Requested-At": h.requestedAt,
    },
  });
}

export async function uploadOk(token: string, h: Header = header()): Promise<string> {
  const res = await upload(token, h, await scanBody(h));
  if (res.status !== 201 && res.status !== 200) throw new Error(`upload: ${res.status} ${await res.text()}`);
  return ((await res.json()) as { id: string }).id;
}

export type Listing = {
  entries: { id: string; era: string; realm: string; faction: string; requestedAt: number; mine: boolean }[];
  rolledBack: string[];
  cursor: string;
  more: boolean;
};

export async function list(token: string, since?: string): Promise<Listing> {
  const res = await call(since === undefined ? "/scans" : `/scans?since=${since}`, { token });
  if (res.status !== 200) throw new Error(`list: ${res.status} ${await res.text()}`);
  return (await res.json()) as Listing;
}

export async function revoke(name: string): Promise<void> {
  const res = await call(`/keys/${name}`, { method: "DELETE", token: ADMIN });
  if (res.status !== 200) throw new Error(`revoke ${name}: ${res.status}`);
}
