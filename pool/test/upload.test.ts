import { describe, expect, it } from "vitest";
import { addKey, call, header, list, scanBody, upload, uploadOk, uploadRaw } from "./helpers";

describe("uploading a Scan", () => {
  it("stores it and serves the same gzipped bytes back by pool ID", async () => {
    const key = await addKey("alice");
    const body = await scanBody();
    const res = await upload(key, header(), body);
    expect(res.status).toBe(201);
    const { id } = (await res.json()) as { id: string };

    const got = await call(`/scans/${id}`, { token: key });
    expect(got.status).toBe(200);
    expect(new Uint8Array(await got.arrayBuffer())).toEqual(body);
  });

  it("rejects an unknown Era", async () => {
    const key = await addKey("alice");
    const h = header({ era: "classic" });
    const res = await upload(key, h, await scanBody(h));
    expect(res.status).toBe(400);
  });

  it.each([
    ["no realm", { realm: "" }],
    ["no faction", { faction: "" }],
    ["a fractional requestedAt", { requestedAt: "1790000000.5" }],
    ["a non-numeric requestedAt", { requestedAt: "yesterday" }],
    ["no requestedAt", { requestedAt: "" }],
  ])("rejects a header with %s", async (_, overrides) => {
    const key = await addKey("alice");
    const h = header(overrides);
    const res = await upload(key, h, await scanBody(header()));
    expect(res.status).toBe(400);
  });

  it("rejects a requestedAt more than 10 minutes in the future", async () => {
    const key = await addKey("alice");
    const h = header({ requestedAt: String(nowSeconds() + 11 * 60) });
    const res = await upload(key, h, await scanBody(h));
    expect(res.status).toBe(400);
  });

  it("accepts a requestedAt a little in the future, for clock skew", async () => {
    const key = await addKey("alice");
    const h = header({ requestedAt: String(nowSeconds() + 9 * 60) });
    const res = await upload(key, h, await scanBody(h));
    expect(res.status).toBe(201);
  });

  it("rejects a body over 2 MB", async () => {
    const key = await addKey("alice");
    const res = await upload(key, header(), gzipLike(2 * MB + 1));
    expect(res.status).toBe(413);
  });

  it("accepts a body of exactly 2 MB", async () => {
    const key = await addKey("alice");
    const res = await upload(key, header(), gzipLike(2 * MB));
    expect(res.status).toBe(201);
  });

  it("rejects a body that isn't gzip", async () => {
    const key = await addKey("alice");
    const res = await upload(key, header(), JSON.stringify({ scan: {} }));
    expect(res.status).toBe(400);
  });

  it("returns the existing pool ID for a second upload of the same Market and requestedAt", async () => {
    const alice = await addKey("alice");
    const bob = await addKey("bob");
    const first = await uploadOk(alice);

    const res = await upload(bob, header(), await scanBody());
    expect(res.status).toBe(200);
    expect(((await res.json()) as { id: string }).id).toBe(first);
  });

  it.each([
    ["an accented realm", "Ragnarös"],
    ["a realm outside Latin-1", "Пиратская бухта"],
  ])("indexes %s as the Brain named it, so a second upload is a duplicate", async (_, realm) => {
    const key = await addKey("alice");
    const h = header({ realm, faction: "Орда" });
    const first = await uploadOk(key, h);

    const { entries } = await list(key);
    expect(entries.map((e) => [e.realm, e.faction])).toEqual([[realm, "Орда"]]);
    const again = await upload(key, h, await scanBody(h));
    expect(again.status).toBe(200);
    expect(((await again.json()) as { id: string }).id).toBe(first);
  });

  it("rejects a realm with a malformed percent escape", async () => {
    const key = await addKey("alice");
    const h = header({ realm: "Ragnar%C3" });
    const res = await uploadRaw(key, h, await scanBody(h));
    expect(res.status).toBe(400);
    expect(await res.text()).toContain("X-Scan-Realm");
  });

  it("404s for a pool ID it never handed out", async () => {
    const key = await addKey("alice");
    expect((await call("/scans/not-a-pool-id", { token: key })).status).toBe(404);
  });
});

const MB = 1024 * 1024;

// A body of `size` bytes that starts like gzip. The Worker never gunzips, so the rest is filler.
function gzipLike(size: number): Uint8Array {
  const bytes = new Uint8Array(size);
  bytes[0] = 0x1f;
  bytes[1] = 0x8b;
  return bytes;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}
