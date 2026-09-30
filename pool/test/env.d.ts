import type { D1Migration } from "@cloudflare/vitest-pool-workers";

declare global {
  namespace Cloudflare {
    interface Env {
      DB: D1Database;
      SCANS: R2Bucket;
      ADMIN_SECRET: string;
      TEST_MIGRATIONS: D1Migration[];
    }
    // Types `exports.default` from "cloudflare:workers" as the Worker's own export.
    interface GlobalProps {
      mainModule: typeof import("../src/index");
    }
  }
}
