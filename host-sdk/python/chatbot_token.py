"""
Mints the short-lived token the chat widget uses to recognise your signed-in user.

Needs ``pip install "pyjwt[crypto]"``. The private key stays on your server.

    CHATBOT_PRIVATE_KEY_FILE=/secure/chatbot-signing-key.pem
"""

import os
import time
import uuid

import jwt

ISSUER = "{{ISSUER}}"
AUDIENCE = "{{AUDIENCE}}"
#: Seconds the token is valid; the chat refuses tokens living longer than 15 minutes.
LIFETIME_SECONDS = 600

with open(os.getenv("CHATBOT_PRIVATE_KEY_FILE", "chatbot-signing-key.pem"), encoding="utf-8") as _key_file:
    PRIVATE_KEY = _key_file.read()


def mint_chatbot_token(user_id: str, tier: str = "user") -> str:
    """
    Args:
        user_id: Your stable, opaque user id (letters, digits, ``_ - : . @``; not an e-mail or phone).
        tier: The user's access tier, e.g. ``user`` or ``premium``.
    """
    now = int(time.time())
    claims = {"sub": str(user_id), "tier": tier, "iss": ISSUER, "aud": AUDIENCE,
              "iat": now, "exp": now + LIFETIME_SECONDS, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


# Example endpoint (Flask). The host page's getToken() calls it; 204 means nobody is signed in.
#
# @app.get("/chatbot-token")
# def chatbot_token():
#     if not current_user.is_authenticated:
#         return "", 204, {"Cache-Control": "no-store"}
#     return mint_chatbot_token(current_user.id), 200, {"Content-Type": "text/plain", "Cache-Control": "no-store"}
