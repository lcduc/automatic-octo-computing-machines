# Personal data flows (PRV-01)

This map is for the client's legal or data-protection reviewer. It covers one
client deployment: one server running the chatbot for one host website.

It describes what the software does. Whether that satisfies Law 91/2025/QH15 on
Personal Data Protection (effective 1 January 2026) and its implementing decree
is for the client's lawyer to assess. The questions to settle are listed at the end.

## Roles

| Party | Role |
|---|---|
| Client (owns the host website and the chatbot server) | Controller of visitor and user data |
| Vendor (builds and operates the chatbot) | Processes data on the client's behalf; administers the server under contract |
| OpenAI (LLM provider, organisation chosen per client) | Sub-processor outside Vietnam (cross-border transfer) |
| Backup target, alert channel, SMTP provider (chosen per client) | Sub-processors, as configured at install |

## What is collected

| Data | From whom | Where it is stored | Kept for (default) |
|---|---|---|---|
| Random visitor id (signed cookie) | Every visitor | Browser cookie; `conversations.end_user_id` | Life of the conversation |
| Host user id (`sub` of the host token) and tier | Signed-in users of the host site | `conversations.user_id`, tickets | Life of the conversation or ticket |
| Chat messages and answers | Visitors | `messages`. Phone numbers, ID numbers, e-mails and bank/card numbers are masked first (`PII_REDACTION_ENABLED`, on by default) | 365 days signed-in, 90 days anonymous, from last activity |
| Voice input (when used) | Visitors | Not stored; transcribed and discarded | — |
| Ratings and comments | Visitors | `feedback` | With the conversation |
| Ticket contact (name, e-mail, phone, details) and consent time | Visitors who ask for a human | `handoff_requests`; masked in the admin web, full view is owner-only and audit-logged | 730 days from opening; open tickets are kept |
| Results of private data tools (e.g. the user's orders) | Client's business database, for the signed-in user only | Sent to the model to write the answer. The answer text is stored; raw rows and tool argument values are not | With the conversation |
| Per-answer trace (route, retrieval scores, timings, tool names) | System | `message_traces` | 90 days |
| Token usage and cost per call | System | `token_usage` | 90 days; daily totals without personal data are kept indefinitely |
| IP address | Every visitor | Only as an unsalted SHA-256 hash inside rate-limit counters. That is pseudonymous, not anonymous: IPv4 hashes can be reversed by brute force | Up to 62 days |
| Admin accounts, admin actions and admin IP | Client and vendor staff | `admin_users`; `admin_audit_log` (append-only) | 1095 days (never less than 365) |
| Eval cases | Copied by staff from answers | `eval_cases`, masked again, no link to the conversation | Until deleted by staff |

Retention periods are set per client by an owner in the admin web. Items under
legal hold are kept past them. See "Privacy and retention" in [DEPLOYMENT.md](DEPLOYMENT.md).

## Where data travels

```text
Visitor browser ──HTTPS──> chat.<domain> (widget + server-side layer, on the client server)
                              │ internal network only
                              ▼
                           API ──> PostgreSQL (same server)
                              │──> model server (same server): embeddings, reranking, OCR
                              │──> client business database (read-only role, private tools only)
                              └──HTTPS──> OpenAI API (outside Vietnam)
Staff browser ──HTTPS──> admin.<domain> (separate domain, never embeddable)
Server ──> backup target (S3 over HTTPS, SFTP, or a mounted path; chosen by the client)
Server ──> alert channel (Telegram / Slack / e-mail): operational messages only
Server ──> SMTP: ticket answers e-mailed to the address the visitor gave
```

- **Stays on the client server:** documents, embeddings, OCR, reranking, the database and logs.
- **Sent to OpenAI:**
  - masked chat text and recent history;
  - retrieved document passages;
  - results of private data tools;
  - voice recordings for transcription;
  - the text checked by moderation, while `MODERATION_ENABLED`.
- **OpenAI terms:** by default OpenAI does not train on API data, and keeps it up to
  30 days for abuse monitoring. Zero Data Retention and regional data residency can be
  arranged per organisation. The chatbot does not ask OpenAI to store completions.
- **Alerts:** these carry service names, counts and error types, not conversation
  content. Ticket alerts count overdue tickets without contact details.
- **Backups:** these contain the whole database, so they hold personal data and follow the
  backup target's location and access control. Nightly backups are kept `keep_days`
  (default 30), so deleted data lingers there until the copies age out.
- **Logs:** application logs are structured JSON with personal data masked, rotated
  at 10 MB × 5 files per container. The reverse proxy writes no access log.

## Rights of the person (PRV-03)

An owner can find a person by host user id, visitor id or ticket e-mail. They can:

- **export** all of that person's conversations, ratings and tickets as JSON;
- **delete** them immediately, overriding retention. Items under legal hold are kept and reported.

Both actions are recorded in the audit log. Copies in existing backups expire with
the backup rotation.

## Consent and notices

- **Chat notice:** the widget always shows that answers come from an AI assistant, may be
  inaccurate, and that sensitive personal data should not be shared (PRV-06).
- **Tickets:** anonymous visitors must accept a notice on how their contact details are
  used before sending them. The acceptance time is stored (PRV-02).
- **Host website:** the client's own privacy notice should mention the chat, the
  categories above and the transfer to OpenAI.

## Questions for the client's legal review

1. Legal basis for processing chat content, and whether the widget notice is enough or
   explicit consent is needed before the first message.
2. Cross-border transfer to OpenAI: the transfer impact assessment and filing required
   under the law and its decree, and whether Zero Data Retention or data residency is needed.
3. Whether results of private data tools (the user's own business records) count as
   sensitive personal data for this client's sector.
4. Retention: whether the defaults fit the client's sector rules. The installer warns
   for finance, healthcare and labour/legal.
5. The data-processing agreement between client and vendor (server access, incident
   notice, deletion at contract end).
6. Where backups may be stored, and for how long.
