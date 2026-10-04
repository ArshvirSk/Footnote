/**
 * Footnote Feeds Edge Worker
 * Deployed to Cloudflare Workers.
 * Intercepts realtime search plugin requests from ChatGPT/Perplexity
 * and proxies them to the Footnote backend or client KB.
 */

export interface Env {
  // KV Namespace binding for rapid API key validation
  API_KEYS: KVNamespace;
  // Footnote backend URL
  BACKEND_URL: string;
  // Shared service token sent as X-Internal-Service (must match EDGE_SERVICE_TOKEN on the API)
  SERVICE_TOKEN: string;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // 1. Health check
    if (url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok" }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // 2. Validate API Key from Bearer token
    const authHeader = request.headers.get("Authorization");
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      return new Response("Unauthorized", { status: 401 });
    }
    const token = authHeader.split(" ")[1];

    // Rapid edge validation using KV
    const clientId = await env.API_KEYS.get(token);
    if (!clientId) {
      return new Response("Forbidden: Invalid API Key", { status: 403 });
    }

    // 3. Handle /search for realtime engine grounding
    if (url.pathname === "/search" && request.method === "GET") {
      const query = url.searchParams.get("q");
      if (!query) {
        return new Response("Missing query parameter 'q'", { status: 400 });
      }

      // Proxy the search to the main API which will execute pgvector similarity search
      // over the approved content corpus for this client.
      const backendUrl = new URL(`/api/v1/clients/${clientId}/edge/search`, env.BACKEND_URL);
      backendUrl.searchParams.set("q", query);

      try {
        const backendRequest = new Request(backendUrl.toString(), {
          method: "GET",
          headers: {
            // Service-to-service auth: must match EDGE_SERVICE_TOKEN on the API
            "X-Internal-Service": env.SERVICE_TOKEN,
          },
        });

        const backendResponse = await fetch(backendRequest);
        
        // Transform or pass-through the JSON-LD response
        const data = await backendResponse.json();
        
        return new Response(JSON.stringify(data), {
          headers: {
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=60",
          },
        });
      } catch (error) {
        return new Response(JSON.stringify({ error: "Internal Server Error" }), { 
          status: 500,
          headers: { "Content-Type": "application/json" }
        });
      }
    }

    return new Response("Not Found", { status: 404 });
  },
};
