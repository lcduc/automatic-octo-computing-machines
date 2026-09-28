// Mints the short-lived token the chat widget uses to recognise your signed-in user.
// Node 18+, no dependencies. The private key stays on your server; never send it to a browser.
//
//   CHATBOT_PRIVATE_KEY_FILE=/secure/chatbot-signing-key.pem node server.js
import { createSign, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";

const PRIVATE_KEY = readFileSync(process.env.CHATBOT_PRIVATE_KEY_FILE ?? "chatbot-signing-key.pem", "utf8");
const ISSUER = "{{ISSUER}}";
const AUDIENCE = "{{AUDIENCE}}";
/** Seconds the token is valid; the chat refuses tokens living longer than 15 minutes. */
const LIFETIME_SECONDS = 600;

const base64url = (value) => Buffer.from(value).toString("base64url");

/**
 * @param {string} userId - Your stable, opaque user id (letters, digits, _ - : . @; not an e-mail or phone).
 * @param {string} tier - The user's access tier, e.g. "user" or "premium".
 * @returns {string} A signed JWT for the widget.
 */
export function mintChatbotToken(userId, tier = "user") {
  const now = Math.floor(Date.now() / 1000);
  const header = base64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = base64url(JSON.stringify({
    sub: String(userId), tier, iss: ISSUER, aud: AUDIENCE, iat: now, exp: now + LIFETIME_SECONDS, jti: randomUUID(),
  }));
  const signature = createSign("RSA-SHA256").update(`${header}.${payload}`).sign(PRIVATE_KEY, "base64url");
  return `${header}.${payload}.${signature}`;
}

// Example endpoint (Express). The host page's getToken() calls it; 204 means nobody is signed in.
//
// app.get("/chatbot-token", (req, res) => {
//   res.set("Cache-Control", "no-store");
//   if (!req.user) return res.status(204).end();
//   res.type("text/plain").send(mintChatbotToken(req.user.id, req.user.plan ?? "user"));
// });
