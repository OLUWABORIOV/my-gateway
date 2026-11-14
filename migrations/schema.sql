CREATE TABLE IF NOT EXISTS payments (
    id VARCHAR(40) PRIMARY KEY,
    order_id VARCHAR(128) NOT NULL,
    customer_id VARCHAR(128) NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    state VARCHAR(20) NOT NULL CHECK (state IN (
        'pending','authorized','captured','voided','refunded','failed','expired')),
    card_last4 VARCHAR(4) NOT NULL,
    card_bin VARCHAR(8) NOT NULL,
    card_fingerprint VARCHAR(64) NOT NULL,
    auth_id VARCHAR(64),
    capture_id VARCHAR(64),
    void_id VARCHAR(64),
    refund_id VARCHAR(64),
    auth_expires_at TIMESTAMPTZ,
    failure_code VARCHAR(64),
    failure_message TEXT,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    in_flight_operation VARCHAR(20),
    in_flight_started_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    authorized_at TIMESTAMPTZ,
    captured_at TIMESTAMPTZ,
    voided_at TIMESTAMPTZ,
    refunded_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    expired_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments (order_id);
CREATE INDEX IF NOT EXISTS idx_payments_customer_created
    ON payments (customer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_state ON payments (state);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_live_order
    ON payments (order_id)
    WHERE state IN ('pending','authorized','captured','voided','refunded');

CREATE TABLE IF NOT EXISTS payment_events (
    id BIGSERIAL PRIMARY KEY,
    payment_id VARCHAR(40) NOT NULL REFERENCES payments (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    operation VARCHAR(20) NOT NULL,
    from_state VARCHAR(20),
    to_state VARCHAR(20),
    bank_reference VARCHAR(64),
    idempotency_key VARCHAR(255),
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payment_events_payment_seq UNIQUE (payment_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_payment_events_payment_id
    ON payment_events (payment_id);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key VARCHAR(255) NOT NULL,
    scope VARCHAR(64) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('in_progress','completed')),
    response_status INTEGER,
    response_body JSONB,
    payment_id VARCHAR(40),
    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (key, scope)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_created_at
    ON idempotency_keys (created_at);

CREATE TABLE IF NOT EXISTS bank_calls (
    id BIGSERIAL PRIMARY KEY,
    payment_id VARCHAR(40),
    operation VARCHAR(20) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    attempt INTEGER NOT NULL,
    status_code INTEGER,
    outcome VARCHAR(16) NOT NULL,
    error_code VARCHAR(64),
    duration_ms INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bank_calls_payment_id ON bank_calls (payment_id);