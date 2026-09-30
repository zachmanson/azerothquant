import { describe, expect, it } from "vitest";
import { type Listing, addKey, call, header, list, uploadOk } from "./helpers";

describe("listing the pool", () => {
  it("lists every Scan with its Market and requestedAt, and flags the caller's own", async () => {
    const alice = await addKey("alice");
    const bob = await addKey("bob");
    const a = await uploadOk(alice, header({ faction: "Horde", requestedAt: "1790000000" }));
    const b = await uploadOk(bob, header({ faction: "Alliance", requestedAt: "1790000060" }));

    const { entries } = await list(alice);
    expect(entries).toEqual([
      { id: a, era: "live", realm: "Forever", faction: "Horde", requestedAt: 1790000000, mine: true },
      { id: b, era: "live", realm: "Forever", faction: "Alliance", requestedAt: 1790000060, mine: false },
    ]);
  });

  it("returns only Scans added after the cursor, and a cursor to continue from", async () => {
    const alice = await addKey("alice");
    const bob = await addKey("bob");
    await uploadOk(alice, header({ requestedAt: "1790000000" }));
    const first = await list(bob);

    const later = await uploadOk(alice, header({ faction: "Alliance", requestedAt: "1790000060" }));
    const second = await list(bob, first.cursor);
    expect(second.entries.map((e) => e.id)).toEqual([later]);

    const third = await list(bob, second.cursor);
    expect(third.entries).toEqual([]);
    expect(third.cursor).toBe(second.cursor);
  });

  it("rejects a cursor that isn't one it handed out", async () => {
    const key = await addKey("alice");
    const res = await call("/scans?since=banana", { token: key });
    expect(res.status).toBe(400);
  });

  it("pages through a long index", async () => {
    const key = await addKey("alice");
    const ids = [];
    for (const realm of ["Forever-1", "Forever-2", "Forever-3"]) ids.push(await uploadOk(key, header({ realm })));

    const page1 = (await (await call("/scans?limit=2", { token: key })).json()) as Listing;
    expect(page1.entries.map((e) => e.id)).toEqual(ids.slice(0, 2));
    expect(page1.more).toBe(true);

    const page2 = (await (await call(`/scans?since=${page1.cursor}&limit=2`, { token: key })).json()) as Listing;
    expect(page2.entries.map((e) => e.id)).toEqual(ids.slice(2));
    expect(page2.more).toBe(false);
  });
});
