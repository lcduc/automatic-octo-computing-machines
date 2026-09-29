-- Demo business database (development, staging, tests): a tiny shop.
--
-- The chatbot connects as chatbot_reader, a read-only role:
--   * products are public and reachable only through the view shop.v_products;
--   * orders are per user: row-level security returns only the rows whose
--     customer_user_id equals app.user_id, which the chatbot sets from the
--     verified host token for every query (never from the model's arguments).
-- The role must already exist (see demo_role.sh); this script is idempotent.

DROP SCHEMA IF EXISTS shop CASCADE;
CREATE SCHEMA shop;

CREATE TABLE shop.products (
    sku text PRIMARY KEY,
    name text NOT NULL,
    price_vnd bigint NOT NULL,
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE shop.orders (
    order_no text PRIMARY KEY,
    customer_user_id text NOT NULL,
    customer_phone text,
    total_vnd bigint NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'paid', 'shipped', 'cancelled')),
    created_at timestamptz NOT NULL
);

ALTER TABLE shop.orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_orders ON shop.orders FOR SELECT TO chatbot_reader
    USING (customer_user_id = current_setting('app.user_id', true));

-- Public data: a definer view, so the reader never touches the table itself.
CREATE VIEW shop.v_products AS
    SELECT sku, name, price_vnd FROM shop.products WHERE active;

-- Per-user data: an invoker view, so the row-level security policy applies to the reader.
CREATE VIEW shop.v_orders WITH (security_invoker = true) AS
    SELECT order_no, customer_user_id, customer_phone, total_vnd, status, created_at FROM shop.orders;

GRANT USAGE ON SCHEMA shop TO chatbot_reader;
GRANT SELECT ON shop.v_products, shop.v_orders TO chatbot_reader;
-- Needed by the invoker view; still filtered by row-level security.
GRANT SELECT ON shop.orders TO chatbot_reader;

INSERT INTO shop.products (sku, name, price_vnd, active) VALUES
    ('TS-01', 'Áo thun cotton', 199000, true),
    ('TS-02', 'Áo sơ mi linen', 459000, true),
    ('SH-01', 'Giày chạy bộ', 1290000, true),
    ('OLD-9', 'Mẫu ngừng bán', 99000, false);

INSERT INTO shop.orders (order_no, customer_user_id, customer_phone, total_vnd, status, created_at) VALUES
    ('DH-1001', 'user-42', '0901234567', 199000, 'paid', now() - interval '40 days'),
    ('DH-1002', 'user-42', '0901234567', 1290000, 'shipped', now() - interval '3 days'),
    ('DH-2001', 'user-99', '0987654321', 459000, 'paid', now() - interval '3 days');
