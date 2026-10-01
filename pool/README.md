# Scan Pool Worker

The Cloudflare Worker behind the Scan Pool (#117, ADR-0026). It holds the member keys and the
Scan index in D1, and the Scan bodies (gzipped JSON, as uploaded) in R2. It never gunzips a Scan:
it checks the cheap things and leaves full validation to each Brain.

## API

Every request carries `Authorization: Bearer <token>`: a member key for `/scans`, the admin
secret for `/keys`.

| Request | Does |
| --- | --- |
| `POST /scans` | Upload a Scan (body: gzipped JSON, ≤ 2 MB). Headers `X-Scan-Era` (`beta` or `live`), `X-Scan-Realm`, `X-Scan-Faction`, `X-Scan-Requested-At` (integer Unix seconds, at most 10 min in the future). Returns `{"id"}`: `201` when stored, `200` with the existing ID when that Market and `requestedAt` is already in the pool. `429` if this key uploaded this Market in the last 10 minutes (wall clock, so a backlog drains one Scan per Market per 10 min). |
| `GET /scans?since=<cursor>&limit=<n>` | `{"entries": [{"id", "era", "realm", "faction", "requestedAt", "mine"}], "rolledBack": [id], "cursor", "more"}`. Entries and rollbacks after the cursor, in order. Omit `since` for the whole pool. `limit` defaults to and is capped at 1000; keep calling with the new cursor while `more` is true. |
| `GET /scans/<id>` | The stored gzipped Scan (`application/gzip`). `404` once rolled back. |
| `POST /keys` | Body `{"name"}`. Returns `{"name", "key"}` (`201`). The key is shown once; only its hash is stored. `409` if the name is taken. |
| `DELETE /keys/<name>` | Revoke the key (`403` on its next request) and roll back all its Scans. |

`401` means a missing or unknown key; `403` a revoked one.

## Local dev

Needs Node 24+. Wrangler comes in as a dev dependency.

```sh
cd pool
npm install
npm test              # vitest in the Workers runtime (Miniflare), local D1 + R2
npm run typecheck
```

To run it by hand, put `ADMIN_SECRET=<anything>` in `pool/.dev.vars` (gitignored), then:

```sh
npx wrangler d1 migrations apply azerothquant-pool --local
npm run dev           # http://localhost:8787
```

## Secrets

- `ADMIN_SECRET`: the bearer token for `/keys`. Set it with `npx wrangler secret put ADMIN_SECRET`.
  The Brain reads the same value from `pool_admin_secret` for `brain pool key add/revoke`.

## Deploying

Once, on the Cloudflare account:

```sh
npx wrangler login
npx wrangler r2 bucket create azerothquant-pool-scans
npx wrangler d1 create azerothquant-pool      # paste its database_id into wrangler.toml
npx wrangler d1 migrations apply azerothquant-pool --remote
npx wrangler r2 bucket lifecycle add azerothquant-pool-scans expire-60d --expire-days 60
npx wrangler secret put ADMIN_SECRET
```

R2 has to be enabled once in the dashboard first (it asks for a card even on the free tier).
The lifecycle rule deletes Scan bodies after 60 days, which keeps the bucket under R2's free
10 GB even if every member scanned nonstop at the upload limit. Brains never fetch pool Scans
older than `pool_backfill_days` (30), so only a `brain pool pull --since` further back than
60 days would get `404`s. A billing notification (Notifications, Usage Based Billing, R2
storage over 8 GB) warns well before anything costs money.

If `wrangler login` doesn't take (it can't hand the login back to some shells), use an API
token instead: the "Edit Cloudflare Workers" template plus Account / D1 / Edit, in
`CLOUDFLARE_API_TOKEN`. Keep it in `pool/.cloudflare-token` (gitignored), not in the repo.

Then, for each change:

```sh
npx wrangler deploy
```

Add a new migration under `migrations/` for any schema change and apply it with `--remote`
before deploying the code that needs it.
