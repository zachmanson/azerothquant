import { describe, expect, it } from "vitest";
import { ADMIN, addKey, call, header, list, revoke, scanBody, upload, uploadOk } from "./helpers";

describe("revoking a key", () => {
  it("locks the key out of listing, fetching and uploading", async () => {
    const key = await addKey("mallory");
    await revoke("mallory");

    expect((await call("/scans", { token: key })).status).toBe(403);
    expect((await call("/scans/anything", { token: key })).status).toBe(403);
    expect((await upload(key, header(), await scanBody())).status).toBe(403);
  });

  it("404s for a name the pool doesn't know", async () => {
    const res = await call("/keys/nobody", { method: "DELETE", token: ADMIN });
    expect(res.status).toBe(404);
  });

  it("rolls back the member's Scans: a later listing names them as rolled back", async () => {
    const alice = await addKey("alice");
    const mallory = await addKey("mallory");
    const good = await uploadOk(alice, header({ faction: "Horde" }));
    const bad = await uploadOk(mallory, header({ faction: "Alliance" }));
    const before = await list(alice);

    await revoke("mallory");

    const after = await list(alice, before.cursor);
    expect(after.rolledBack).toEqual([bad]);
    expect(after.entries).toEqual([]);
    expect((await call(`/scans/${bad}`, { token: alice })).status).toBe(404);
    expect((await call(`/scans/${good}`, { token: alice })).status).toBe(200);
  });

  it("leaves rolled-back Scans out of a fresh listing", async () => {
    const alice = await addKey("alice");
    const mallory = await addKey("mallory");
    const good = await uploadOk(alice, header({ faction: "Horde" }));
    await uploadOk(mallory, header({ faction: "Alliance" }));
    await revoke("mallory");

    const fresh = await list(alice);
    expect(fresh.entries.map((e) => e.id)).toEqual([good]);
  });

  it("frees the Market and requestedAt for an honest upload", async () => {
    const alice = await addKey("alice");
    const mallory = await addKey("mallory");
    const bad = await uploadOk(mallory);
    await revoke("mallory");

    const res = await upload(alice, header(), await scanBody());
    expect(res.status).toBe(201);
    expect(((await res.json()) as { id: string }).id).not.toBe(bad);
  });
});
