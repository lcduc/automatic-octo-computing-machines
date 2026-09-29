-- For the client's database administrator: the read-only access the chatbot needs.
-- Run as a superuser of the business database, after replacing the placeholders.
-- `chatbot preflight` then checks the role really cannot write (TOOL-05).

-- 1. A login role that can read, never write, and never bypass row-level security.
CREATE ROLE chatbot_reader LOGIN PASSWORD '<a long random password>'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE chatbot_reader SET default_transaction_read_only = on;
ALTER ROLE chatbot_reader SET statement_timeout = '3s';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- 2. Views exposing only the columns the chatbot's tools need. Grant SELECT on
--    these views only, never on base tables with data the chatbot must not see.
-- CREATE VIEW reporting.v_products AS SELECT sku, name, price FROM sales.products WHERE active;
-- GRANT USAGE ON SCHEMA reporting TO chatbot_reader;
-- GRANT SELECT ON reporting.v_products TO chatbot_reader;

-- 3. Per-user data: the chatbot sets app.user_id to the signed-in user's id
--    (from the host site's token) before every query. Filter on it with
--    row-level security so a query can only ever see that user's rows:
-- ALTER TABLE sales.orders ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY chatbot_own_orders ON sales.orders FOR SELECT TO chatbot_reader
--     USING (customer_id = current_setting('app.user_id', true));
-- CREATE VIEW reporting.v_orders WITH (security_invoker = true) AS
--     SELECT order_no, customer_id, total, status, created_at FROM sales.orders;
-- GRANT SELECT ON reporting.v_orders, sales.orders TO chatbot_reader;

-- 4. Give the integrator the connection URL for the installer's [business_db] answer:
--    postgresql+asyncpg://chatbot_reader:<password>@<host>:5432/<database>
