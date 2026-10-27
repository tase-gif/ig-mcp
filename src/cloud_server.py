"""Authenticated Streamable HTTP entry point for a single-owner deployment."""
import contextlib
import hmac
import os

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .instagram_mcp_server import InstagramMCPServer
from . import instagram_mcp_server as upstream


def create_app():
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("Set MCP_AUTH_TOKEN to a random secret of at least 32 characters")
    server = InstagramMCPServer()
    manager = StreamableHTTPSessionManager(
        app=server.server, json_response=True, stateless=True
    )

    async def mcp(scope, receive, send):
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"authorization", b"")
        expected = ("Bearer " + token).encode()
        if not hmac.compare_digest(supplied, expected):
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)

    async def health(request):
        # Liveness only: no credentials or Instagram API calls in health checks.
        return JSONResponse({"status": "ok"})

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            try:
                yield
            finally:
                if upstream.instagram_client is not None:
                    await upstream.instagram_client.close()
                    upstream.instagram_client = None

    return Starlette(
        routes=[Route("/healthz", health), Mount("/mcp", app=mcp)],
        lifespan=lifespan,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
