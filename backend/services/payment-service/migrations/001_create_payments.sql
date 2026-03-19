-- 001_create_payments.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE payment_status AS ENUM ('pending', 'processing', 'success', 'failed', 'refunded');

CREATE TABLE IF NOT EXISTS payments (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id             UUID NOT NULL,
    user_id              UUID NOT NULL,
    amount               NUMERIC(12, 2) NOT NULL,
    currency             VARCHAR(3) NOT NULL DEFAULT 'USD',
    status               payment_status NOT NULL DEFAULT 'pending',
    provider             VARCHAR(50) NOT NULL DEFAULT 'stripe',
    provider_payment_id  VARCHAR(255),
    idempotency_key      VARCHAR(255) UNIQUE NOT NULL,
    error_message        TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_idempotency_key ON payments(idempotency_key);
