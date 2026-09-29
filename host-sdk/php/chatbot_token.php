<?php
// Mints the short-lived token the chat widget uses to recognise your signed-in user.
// PHP 7.4+ with the openssl extension, no other dependency. The private key stays on your server.
//
//   CHATBOT_PRIVATE_KEY_FILE=/secure/chatbot-signing-key.pem

const CHATBOT_ISSUER = '{{ISSUER}}';
const CHATBOT_AUDIENCE = '{{AUDIENCE}}';
/** Seconds the token is valid; the chat refuses tokens living longer than 15 minutes. */
const CHATBOT_TOKEN_LIFETIME = 600;

function chatbot_base64url(string $data): string
{
    return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
}

/**
 * @param string $userId Your stable, opaque user id (letters, digits, _ - : . @; not an e-mail or phone).
 * @param string $tier   The user's access tier, e.g. "user" or "premium".
 */
function mint_chatbot_token(string $userId, string $tier = 'user'): string
{
    $now = time();
    $flags = JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR;
    $header = chatbot_base64url(json_encode(['alg' => 'RS256', 'typ' => 'JWT'], $flags));
    $payload = chatbot_base64url(json_encode([
        'sub' => $userId, 'tier' => $tier, 'iss' => CHATBOT_ISSUER, 'aud' => CHATBOT_AUDIENCE,
        'iat' => $now, 'exp' => $now + CHATBOT_TOKEN_LIFETIME, 'jti' => bin2hex(random_bytes(16)),
    ], $flags));
    $keyFile = getenv('CHATBOT_PRIVATE_KEY_FILE') ?: __DIR__ . '/chatbot-signing-key.pem';
    $key = openssl_pkey_get_private(file_get_contents($keyFile));
    if ($key === false || !openssl_sign("$header.$payload", $signature, $key, OPENSSL_ALGO_SHA256)) {
        throw new RuntimeException('Cannot sign the chatbot token: check CHATBOT_PRIVATE_KEY_FILE');
    }
    return "$header.$payload." . chatbot_base64url($signature);
}

// Example endpoint, e.g. /chatbot-token.php. The host page's getToken() calls it; 204 = nobody signed in.
//
// session_start();
// header('Cache-Control: no-store');
// if (empty($_SESSION['user_id'])) { http_response_code(204); exit; }
// header('Content-Type: text/plain');
// echo mint_chatbot_token((string) $_SESSION['user_id'], $_SESSION['plan'] ?? 'user');
