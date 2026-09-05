import { describe, expect, it, mock } from "bun:test";
import { GET, POST } from "../../../app/api/proxy/[...path]/route";
import { NextRequest } from "next/server";

describe("Next.js Server-Side API Proxy / BFF", () => {
  it("injects FASTAPI_API_KEY and forwards request to FastAPI with no-store headers", async () => {
    process.env.FASTAPI_BACKEND_URL = "http://127.0.0.1:8000";
    process.env.FASTAPI_API_KEY = "SECRET_SERVER_TOKEN_777";

    const originalFetch = globalThis.fetch;
    let interceptedUrl = "";
    let interceptedHeaders: any = {};

    globalThis.fetch = mock(async (url: any, options: any) => {
      interceptedUrl = url.toString();
      interceptedHeaders = options.headers;
      return new Response(JSON.stringify({ status: "ok", strategy: "short_strangle" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    try {
      const request = new NextRequest("http://localhost:3000/api/proxy/api/v1/status?filter=active");
      const response = await GET(request, { params: { path: ["api", "v1", "status"] } });

      expect(response.status).toBe(200);
      expect(interceptedUrl).toBe("http://127.0.0.1:8000/api/v1/status?filter=active");
      expect(interceptedHeaders["X-API-Key"]).toBe("SECRET_SERVER_TOKEN_777");

      // Verify no-store private cache headers
      expect(response.headers.get("Cache-Control")).toContain("no-store");
      expect(response.headers.get("Cache-Control")).toContain("private");
      expect(response.headers.get("Pragma")).toBe("no-cache");

      const body = await response.json();
      expect(body.status).toBe("ok");
      // Key is never returned in client response
      expect(JSON.stringify(body)).not.toContain("SECRET_SERVER_TOKEN_777");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("handles POST requests (e.g. kill-switch or reconcile) securely through proxy", async () => {
    process.env.FASTAPI_BACKEND_URL = "http://127.0.0.1:8000";
    process.env.FASTAPI_API_KEY = "SECRET_SERVER_TOKEN_777";

    const originalFetch = globalThis.fetch;
    let interceptedMethod = "";
    let interceptedHeaders: any = {};

    globalThis.fetch = mock(async (url: any, options: any) => {
      interceptedMethod = options.method;
      interceptedHeaders = options.headers;
      return new Response(JSON.stringify({ status: "KILL_SWITCH_ACTIVATED" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    try {
      const request = new NextRequest("http://localhost:3000/api/proxy/api/v1/kill-switch", {
        method: "POST",
      });
      const response = await POST(request, { params: { path: ["api", "v1", "kill-switch"] } });

      expect(response.status).toBe(200);
      expect(interceptedMethod).toBe("POST");
      expect(interceptedHeaders["X-API-Key"]).toBe("SECRET_SERVER_TOKEN_777");

      const body = await response.json();
      expect(body.status).toBe("KILL_SWITCH_ACTIVATED");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("handles backend gateway error cleanly without exposing server details", async () => {
    process.env.FASTAPI_BACKEND_URL = "http://127.0.0.1:8000";
    const originalFetch = globalThis.fetch;

    globalThis.fetch = mock(async () => {
      throw new Error("ECONNREFUSED 127.0.0.1:8000");
    });

    try {
      const request = new NextRequest("http://localhost:3000/api/proxy/api/v1/status");
      const response = await GET(request, { params: { path: ["api", "v1", "status"] } });

      expect(response.status).toBe(502);
      const body = await response.json();
      expect(body.detail).toContain("Backend Gateway Error");
      expect(response.headers.get("Cache-Control")).toContain("no-store");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
