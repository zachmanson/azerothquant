import { describe, expect, it } from "vitest";
import { ADMIN, addKey, call } from "./helpers";

describe("member keys", () => {
  it("a key the admin adds can list the pool", async () => {
    const key = await addKey("alice");
    const res = await call("/scans", { token: key });
    expect(res.status).toBe(200);
  });

  it("rejects a request with no key", async () => {
    const res = await call("/scans");
    expect(res.status).toBe(401);
  });

  it("rejects a key the pool never issued", async () => {
    const res = await call("/scans", { token: "not-a-real-key" });
    expect(res.status).toBe(401);
  });

  it("does not let the admin secret stand in for a member key", async () => {
    const res = await call("/scans", { token: ADMIN });
    expect(res.status).toBe(401);
  });
});

describe("admin-only key endpoints", () => {
  it("won't add a key without the admin secret", async () => {
    const res = await call("/keys", { method: "POST", body: JSON.stringify({ name: "mallory" }) });
    expect(res.status).toBe(401);
  });

  it("won't add a key for a member key", async () => {
    const key = await addKey("alice");
    const res = await call("/keys", { method: "POST", token: key, body: JSON.stringify({ name: "mallory" }) });
    expect(res.status).toBe(401);
  });

  it("won't revoke a key for a member key", async () => {
    const alice = await addKey("alice");
    await addKey("bob");
    const res = await call("/keys/bob", { method: "DELETE", token: alice });
    expect(res.status).toBe(401);
  });

  it("refuses a name that's already taken", async () => {
    await addKey("alice");
    const res = await call("/keys", { method: "POST", token: ADMIN, body: JSON.stringify({ name: "alice" }) });
    expect(res.status).toBe(409);
  });
});
