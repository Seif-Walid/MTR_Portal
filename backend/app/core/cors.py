"""CORS, split by who may call what.

The portal's own frontend origins get credentialed CORS (cookies) on the whole
API. The public marketing website gets CORS only on /api/public/*, and never
with credentials: mindtechrobotics.com and portal.mindtechrobotics.com are the
same *site*, so a browser sends the portal's SameSite=Lax session cookie along
with the website's requests. Letting the website read credentialed responses
would let any script running there (a compromised dependency or deploy) read
whatever the signed-in visitor can — the whole member list, for an admin.
"""

from starlette.middleware.cors import CORSMiddleware

PUBLIC_PREFIX = "/api/public/"


class SplitCORSMiddleware:
    def __init__(self, app, *, portal_origins: list[str], public_origins: list[str]) -> None:
        self.portal = CORSMiddleware(
            app, allow_origins=portal_origins, allow_credentials=True,
            allow_methods=["*"], allow_headers=["*"],
        )
        self.public = CORSMiddleware(
            app, allow_origins=list(dict.fromkeys([*portal_origins, *public_origins])),
            allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["content-type"],
        )

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith(PUBLIC_PREFIX):
            await self.public(scope, receive, send)
        else:
            await self.portal(scope, receive, send)
