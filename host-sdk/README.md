# Chat widget: host-site integration

For the developers of the website that embeds the chat (`{{HOST_ORIGIN}}`).
The chat runs at `https://{{CHAT_DOMAIN}}`.

## Anonymous visitors only

Add one line before `</body>`:

```html
<script src="https://{{CHAT_DOMAIN}}/embed.js" defer></script>
```

## Signed-in users

The chat recognises your signed-in users so it can answer from their own data.
Your backend signs a short-lived token (JWT, RS256) for the current user and your
page hands it to the chat. The chat verifies the signature with the public key
it already has; the private key never leaves your server.

1. **Keep the private key on your server** (`chatbot-signing-key.pem` in this
   bundle), outside the web root, readable only by your app. Delete every other
   copy, including this bundle's, once it is installed.
2. **Add a token endpoint** for the signed-in user (e.g. `GET /chatbot-token`):
   copy `node/chatbot-token.mjs`, `php/chatbot_token.php` or
   `python/chatbot_token.py`. Answer `204` when nobody is signed in, and always
   send `Cache-Control: no-store`.
3. **Wire the page**: `host-page.html` shows the two snippets (the token
   callback, then `embed.js`). If sign-in or sign-out happens without a page
   reload, call `Chatbot.login()` / `Chatbot.logout()`.

### Token contract

| Claim  | Value                                                                     |
|--------|---------------------------------------------------------------------------|
| `sub`  | Your stable user id: 1–128 of `A-Z a-z 0-9 _ - : . @`, not an e-mail or phone |
| `tier` | `user` or `premium` (as agreed per deployment)                            |
| `iss`  | `{{ISSUER}}`                                                              |
| `aud`  | `{{AUDIENCE}}`                                                            |
| `iat`, `exp` | Issue and expiry time; `exp - iat` at most 900 seconds (use 600)    |
| `jti`  | A new random id per token                                                 |

The chat refuses tokens that fail any of these checks. A token is bound to the
browser that first used it, so a copied token is useless elsewhere. Mint a new
one whenever the chat asks (`getToken` is called before each expiry).

### Security notes

- Serve the token endpoint only to your own pages (same-origin, your session
  cookie). Never mint tokens for a user id taken from a query string.
- Sign-out must call `Chatbot.logout()` (or reload the page): the chat then
  hides that user's history immediately.
