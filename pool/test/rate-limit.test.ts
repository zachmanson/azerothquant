import { afterEach, describe, expect, it, vi } from "vitest";
import { addKey, header, scanBody, upload, uploadOk } from "./helpers";

async function uploadStatus(key: string, overrides: Parameters<typeof header>[0]): Promise<number> {
  const h = header(overrides);
  return (await upload(key, h, await scanBody(h))).status;
}

describe("rate limit: one upload per key per Market per 10 minutes", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("rejects a second Scan of the same Market from the same key", async () => {
    const key = await addKey("alice");
    await uploadOk(key, header({ requestedAt: "1790000000" }));
    expect(await uploadStatus(key, { requestedAt: "1790000900" })).toBe(429);
  });

  it("lets the same key upload another Market", async () => {
    const key = await addKey("alice");
    await uploadOk(key, header({ faction: "Horde" }));
    expect(await uploadStatus(key, { faction: "Alliance" })).toBe(201);
  });

  it("lets another key upload the same Market", async () => {
    await uploadOk(await addKey("alice"), header({ requestedAt: "1790000000" }));
    expect(await uploadStatus(await addKey("bob"), { requestedAt: "1790000900" })).toBe(201);
  });

  it("lets the same key upload the Market again once 10 minutes have passed", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
    const key = await addKey("alice");
    await uploadOk(key, header({ requestedAt: "1790000000" }));

    vi.setSystemTime(new Date("2026-09-30T12:09:59Z"));
    expect(await uploadStatus(key, { requestedAt: "1790000900" })).toBe(429);
    vi.setSystemTime(new Date("2026-09-30T12:10:01Z"));
    expect(await uploadStatus(key, { requestedAt: "1790000900" })).toBe(201);
  });
});
