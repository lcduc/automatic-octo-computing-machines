"""
Append-only audit trail of admin writes and sign-in attempts (checklist Invariant 8).
"""

# Standard library imports
import json
import logging
from typing import Any

# Local imports
from services.audit_service import AuditRecord
from utils.request_context import request_id_var
from .asgi_helpers import header_value

logger = logging.getLogger(__name__)

#: The admin API mounted by api/routes (``/api/v1`` + ``/admin``).
ADMIN_API_PREFIX = "/api/v1/admin/"
#: Methods that change state and are therefore audited.
AUDITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Largest request/response body kept verbatim in an audit entry.
AUDIT_MAX_BODY_BYTES = 16_384
#: Sign-ins are audited with the submitted e-mail, since no one is signed in yet.
LOGIN_PATH_SUFFIX = "/auth/login"


class AdminAuditMiddleware:
    """
    Records every admin write (POST/PATCH/DELETE under the admin API) and every
    sign-in attempt in the append-only audit log, after the response is sent.

    The actor is the principal ``require_admin`` stored on the request state;
    JSON bodies up to ``AUDIT_MAX_BODY_BYTES`` are kept (secrets are redacted by
    the audit service), anything larger or non-JSON is summarised.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] not in AUDITED_METHODS
            or not scope["path"].startswith(ADMIN_API_PREFIX)
        ):
            return await self.app(scope, receive, send)
        request_body = bytearray()
        response_body = bytearray()
        response = {"status": 500, "content_type": ""}

        async def capturing_receive():
            message = await receive()
            if message["type"] == "http.request" and len(request_body) <= AUDIT_MAX_BODY_BYTES:
                request_body.extend(message.get("body", b""))
            return message

        async def capturing_send(message):
            if message["type"] == "http.response.start":
                response["status"] = message["status"]
                headers = dict(message.get("headers", []))
                response["content_type"] = headers.get(b"content-type", b"").decode("latin-1")
            elif message["type"] == "http.response.body" and len(response_body) <= AUDIT_MAX_BODY_BYTES:
                response_body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, capturing_receive, capturing_send)
        finally:
            await self._record(scope, request_body, response_body, response)

    @staticmethod
    def _decode(body: bytes, content_type: str) -> Any:
        """A JSON body as data; anything else as a short description."""
        if not body:
            return None
        if "json" in content_type and len(body) <= AUDIT_MAX_BODY_BYTES:
            try:
                return json.loads(body)
            except ValueError:
                logger.warning("Audited body is not valid JSON (%d bytes)", len(body))
        return {"omitted": content_type or "unknown", "bytes": len(body)}

    async def _record(self, scope, request_body: bytes, response_body: bytes, response: dict) -> None:
        """Write the entry; a failure is logged, never raised (the change already happened)."""
        container = getattr(scope["app"].state, "container", None)
        if container is None:
            return
        principal = scope.get("state", {}).get("admin")
        request_data = self._decode(bytes(request_body), header_value(scope, b"content-type"))
        actor_email = principal.email if principal else None
        if actor_email is None and scope["path"].endswith(LOGIN_PATH_SUFFIX) and isinstance(request_data, dict):
            actor_email = str(request_data.get("email", ""))[:255] or None
        client = scope.get("client")
        try:
            await container.audit.record(
                AuditRecord(
                    method=scope["method"],
                    path=scope["path"],
                    status_code=response["status"],
                    actor_id=principal.id if principal else None,
                    actor_email=actor_email,
                    actor_role=principal.role if principal else None,
                    request_id=request_id_var.get(None),
                    client_ip=client[0] if client else None,
                    request_body=request_data,
                    response_body=self._decode(bytes(response_body), response["content_type"]),
                )
            )
        except Exception:
            logger.exception("Could not write the audit entry for %s %s", scope["method"], scope["path"])
