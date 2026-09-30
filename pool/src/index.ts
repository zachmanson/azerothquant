export interface Env {
  DB: D1Database;
  SCANS: R2Bucket;
  ADMIN_SECRET: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const route = `${request.method} ${url.pathname}`;

    if (url.pathname === "/keys" || url.pathname.startsWith("/keys/")) {
      if (!isAdmin(request, env)) return error(401, "admin secret required");
      if (route === "POST /keys") return addKey(request, env);
      if (request.method === "DELETE") {
        return revokeKey(env, decodeURIComponent(url.pathname.slice("/keys/".length)));
      }
      return error(404, "not found");
    }

    const member = await authenticate(request, env);
    if (member instanceof Response) return member;

    if (route === "POST /scans") return uploadScan(request, env, member);
    if (route === "GET /scans") return listScans(url, env, member);
    if (request.method === "GET" && url.pathname.startsWith("/scans/")) {
      return getScan(env, url.pathname.slice("/scans/".length));
    }
    return error(404, "not found");
  },
} satisfies ExportedHandler<Env>;

type Member = { name: string };

function bearer(request: Request): string | null {
  const header = request.headers.get("Authorization") ?? "";
  return header.startsWith("Bearer ") ? header.slice("Bearer ".length) : null;
}

function isAdmin(request: Request, env: Env): boolean {
  const token = bearer(request);
  if (token === null || !env.ADMIN_SECRET) return false;
  const a = new TextEncoder().encode(token);
  const b = new TextEncoder().encode(env.ADMIN_SECRET);
  return a.byteLength === b.byteLength && crypto.subtle.timingSafeEqual(a, b);
}

async function authenticate(request: Request, env: Env): Promise<Member | Response> {
  const token = bearer(request);
  if (token === null) return error(401, "member key required");
  const row = await env.DB.prepare("SELECT name, revoked_at FROM keys WHERE key_hash = ?")
    .bind(await sha256(token))
    .first<{ name: string; revoked_at: number | null }>();
  if (row === null) return error(401, "unknown key");
  if (row.revoked_at !== null) return error(403, "key revoked");
  return { name: row.name };
}

async function addKey(request: Request, env: Env): Promise<Response> {
  const body = await request.json<{ name?: unknown }>().catch(() => ({}) as { name?: unknown });
  const name = body.name;
  if (typeof name !== "string" || !isShortText(name)) return error(400, "name must be 1-64 characters");
  const key = randomKey();
  const inserted = await env.DB.prepare(
    "INSERT INTO keys (name, key_hash, created_at) VALUES (?, ?, ?) ON CONFLICT (name) DO NOTHING",
  )
    .bind(name, await sha256(key), nowSeconds())
    .run();
  if (inserted.meta.changes === 0) return error(409, "name already taken");
  return json({ name, key }, 201);
}

// Revoking a key rolls back all its Scans: they leave the index, their IDs go into the
// rolled-back list every Brain sees on its next pull, and their bodies are deleted.
async function revokeKey(env: Env, name: string): Promise<Response> {
  const known = await env.DB.prepare("SELECT 1 FROM keys WHERE name = ?").bind(name).first();
  if (known === null) return error(404, "no such key");

  await env.DB.batch([
    env.DB.prepare("UPDATE keys SET revoked_at = ? WHERE name = ? AND revoked_at IS NULL").bind(nowSeconds(), name),
    env.DB.prepare(
      `INSERT INTO events (kind, scan_id)
       SELECT 'rollback', id FROM scans WHERE uploader = ? AND rolled_back = 0 ORDER BY requested_at`,
    ).bind(name),
    env.DB.prepare("UPDATE scans SET rolled_back = 1 WHERE uploader = ?").bind(name),
  ]);
  // Read after the batch, so a Scan uploaded just before it still loses its body.
  const { results } = await env.DB.prepare("SELECT id FROM scans WHERE uploader = ?").bind(name).all<{ id: string }>();
  const ids = results.map((row) => row.id);
  for (let i = 0; i < ids.length; i += R2_DELETE_BATCH) {
    await env.SCANS.delete(ids.slice(i, i + R2_DELETE_BATCH).map(objectKey));
  }
  return json({ name, revoked: true });
}

type ScanHeader = { era: string; realm: string; faction: string; requestedAt: number };

const ERAS = ["beta", "live"];
const MAX_FUTURE_SECONDS = 10 * 60;
const RATE_LIMIT_SECONDS = 10 * 60;
const MAX_PAGE = 1000;
const R2_DELETE_BATCH = 1000;
const MAX_BODY_BYTES = 2 * 1024 * 1024;

// The cheap header check: the Worker never gunzips the body, so the Brain sends the Scan's
// Market and requestedAt as headers. Every Brain fully validates the body when it pulls it.
function readHeader(request: Request): ScanHeader | string {
  const h = request.headers;
  const era = h.get("X-Scan-Era") ?? "";
  if (!ERAS.includes(era)) return "X-Scan-Era must be one of " + ERAS.join(", ");
  const realm = h.get("X-Scan-Realm") ?? "";
  if (!isShortText(realm)) return "X-Scan-Realm is required";
  const faction = h.get("X-Scan-Faction") ?? "";
  if (!isShortText(faction)) return "X-Scan-Faction is required";
  const requestedAt = h.get("X-Scan-Requested-At") ?? "";
  if (!/^[0-9]{1,12}$/.test(requestedAt)) return "X-Scan-Requested-At must be an integer (Unix seconds)";
  if (Number(requestedAt) > nowSeconds() + MAX_FUTURE_SECONDS) {
    return `X-Scan-Requested-At is more than ${MAX_FUTURE_SECONDS / 60} minutes in the future`;
  }
  return { era, realm, faction, requestedAt: Number(requestedAt) };
}

function isShortText(value: string): boolean {
  return value.length > 0 && value.length <= 64;
}

async function uploadScan(request: Request, env: Env, member: Member): Promise<Response> {
  const scan = readHeader(request);
  if (typeof scan === "string") return error(400, scan);
  const body = await readCapped(request, MAX_BODY_BYTES);
  if (body === null) return error(413, `Scan is over ${MAX_BODY_BYTES / 1024 / 1024} MB gzipped`);
  if (body[0] !== 0x1f || body[1] !== 0x8b) return error(400, "Scan body must be gzipped");
  const existing = await findLiveScan(env, scan);
  if (existing !== null) return json({ id: existing }, 200);
  if (await uploadedRecently(env, member, scan)) {
    return error(429, `this key already uploaded a Scan of this Market in the last ${RATE_LIMIT_SECONDS / 60} minutes`);
  }

  const id = crypto.randomUUID();
  await env.SCANS.put(objectKey(id), body, { httpMetadata: { contentType: "application/gzip" } });
  let inserted: D1Result[];
  try {
    // A batch is one transaction, and revokeKey's is too: the insert happens only if the key is
    // still live, so an upload racing a revoke either lands before it (and is rolled back) or not at all.
    inserted = await env.DB.batch([
      env.DB.prepare(
        `INSERT INTO scans (id, era, realm, faction, requested_at, uploader, uploaded_at)
         SELECT ?, ?, ?, ?, ?, ?, ?
         WHERE EXISTS (SELECT 1 FROM keys WHERE name = ? AND revoked_at IS NULL)`,
      ).bind(id, scan.era, scan.realm, scan.faction, scan.requestedAt, member.name, nowSeconds(), member.name),
      env.DB.prepare(
        "INSERT INTO events (kind, scan_id) SELECT 'add', id FROM scans WHERE id = ?",
      ).bind(id),
    ]);
  } catch (e) {
    // Lost a race with an identical upload: keep theirs.
    await env.SCANS.delete(objectKey(id));
    const winner = await findLiveScan(env, scan);
    if (winner !== null) return json({ id: winner }, 200);
    throw e;
  }
  if (inserted[0].meta.changes === 0) {
    await env.SCANS.delete(objectKey(id));
    return error(403, "key revoked");
  }
  return json({ id }, 201);
}

async function uploadedRecently(env: Env, member: Member, scan: ScanHeader): Promise<boolean> {
  const recent = await env.DB.prepare(
    `SELECT 1 FROM scans
     WHERE uploader = ? AND era = ? AND realm = ? AND faction = ? AND uploaded_at > ?`,
  )
    .bind(member.name, scan.era, scan.realm, scan.faction, nowSeconds() - RATE_LIMIT_SECONDS)
    .first();
  return recent !== null;
}

async function findLiveScan(env: Env, scan: ScanHeader): Promise<string | null> {
  return env.DB.prepare(
    `SELECT id FROM scans
     WHERE era = ? AND realm = ? AND faction = ? AND requested_at = ? AND rolled_back = 0`,
  )
    .bind(scan.era, scan.realm, scan.faction, scan.requestedAt)
    .first<string>("id");
}

// Reads the body, or returns null as soon as it passes `max` bytes, so an oversized upload
// is never buffered whole.
async function readCapped(request: Request, max: number): Promise<Uint8Array | null> {
  const declared = Number(request.headers.get("Content-Length"));
  if (declared > max) return null;
  if (request.body === null) return new Uint8Array();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for await (const chunk of request.body) {
    size += chunk.byteLength;
    if (size > max) return null;
    chunks.push(chunk);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

type EventRow = {
  seq: number;
  kind: "add" | "rollback";
  id: string;
  era: string;
  realm: string;
  faction: string;
  requested_at: number;
  uploader: string;
  rolled_back: number;
};

async function listScans(url: URL, env: Env, member: Member): Promise<Response> {
  const sinceParam = url.searchParams.get("since") ?? "0";
  if (!/^[0-9]{1,15}$/.test(sinceParam)) return error(400, "since must be a cursor from an earlier listing");
  const since = Number(sinceParam);
  const limitParam = url.searchParams.get("limit") ?? String(MAX_PAGE);
  if (!/^[0-9]{1,6}$/.test(limitParam) || Number(limitParam) === 0) return error(400, "limit must be a positive integer");
  const limit = Math.min(Number(limitParam), MAX_PAGE);
  const { results } = await env.DB.prepare(
    `SELECT e.seq, e.kind, s.id, s.era, s.realm, s.faction, s.requested_at, s.uploader, s.rolled_back
     FROM events e JOIN scans s ON s.id = e.scan_id
     WHERE e.seq > ? ORDER BY e.seq LIMIT ?`,
  )
    .bind(since, limit + 1)
    .all<EventRow>();
  // One extra row tells us whether there's another page.
  const more = results.length > limit;
  if (more) results.pop();
  const entries = results
    .filter((row) => row.kind === "add" && row.rolled_back === 0)
    .map((row) => ({
      id: row.id,
      era: row.era,
      realm: row.realm,
      faction: row.faction,
      requestedAt: row.requested_at,
      mine: row.uploader === member.name,
    }));
  const rolledBack = results.filter((row) => row.kind === "rollback").map((row) => row.id);
  const cursor = results.length > 0 ? results[results.length - 1].seq : since;
  return json({ entries, rolledBack, cursor: String(cursor), more });
}

async function getScan(env: Env, id: string): Promise<Response> {
  const live = await env.DB.prepare("SELECT 1 FROM scans WHERE id = ? AND rolled_back = 0").bind(id).first();
  if (live === null) return error(404, "no such Scan");
  const object = await env.SCANS.get(objectKey(id));
  if (object === null) return error(404, "no such Scan");
  return new Response(object.body, { headers: { "Content-Type": "application/gzip" } });
}

function objectKey(id: string): string {
  return `scans/${id}.json.gz`;
}

function randomKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return toHex(bytes);
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return toHex(new Uint8Array(digest));
}

function toHex(bytes: Uint8Array): string {
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

function error(status: number, message: string): Response {
  return json({ error: message }, status);
}
