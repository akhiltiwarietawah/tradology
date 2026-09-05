import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Server-Side API Proxy / BFF (Backend-For-Frontend).
 *
 * Securely forwards browser requests to the internal FastAPI backend,
 * injecting the private server-side API Key without exposing it to the browser.
 */
async function handleProxy(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  const backendUrl = (
    process.env.FASTAPI_BACKEND_URL || "http://127.0.0.1:8000"
  ).replace(/\/$/, "");
  const serverApiKey =
    process.env.FASTAPI_API_KEY || process.env.DASHBOARD_API_KEY || "";

  const path = params.path ? params.path.join("/") : "";
  const queryString = request.nextUrl.search || "";
  const targetUrl = `${backendUrl}/${path}${queryString}`;

  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };

  // Inject server-side API key for FastAPI authentication
  if (serverApiKey) {
    headers["X-API-Key"] = serverApiKey;
  }

  try {
    const fetchOptions: RequestInit = {
      method: request.method,
      headers,
      cache: "no-store",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      try {
        const bodyText = await request.text();
        if (bodyText) {
          fetchOptions.body = bodyText;
        }
      } catch {
        // No body
      }
    }

    const response = await fetch(targetUrl, fetchOptions);

    let data: any;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      data = await response.text();
    }

    const nextResponse =
      typeof data === "string"
        ? new NextResponse(data, { status: response.status })
        : NextResponse.json(data, { status: response.status });

    // Enforce private, non-cacheable responses for all financial & operational data
    nextResponse.headers.set(
      "Cache-Control",
      "no-store, no-cache, must-revalidate, private"
    );
    nextResponse.headers.set("Pragma", "no-cache");
    nextResponse.headers.set("Expires", "0");

    return nextResponse;
  } catch (error: any) {
    console.error(`[API Proxy Error] Failed to reach ${targetUrl}:`, error);
    return NextResponse.json(
      {
        detail: "Backend Gateway Error: Unable to connect to trading engine",
        error: error.message || "Connection refused",
      },
      {
        status: 502,
        headers: {
          "Cache-Control": "no-store, no-cache, must-revalidate, private",
        },
      }
    );
  }
}

export async function GET(
  request: NextRequest,
  context: { params: { path: string[] } }
) {
  return handleProxy(request, context);
}

export async function POST(
  request: NextRequest,
  context: { params: { path: string[] } }
) {
  return handleProxy(request, context);
}
