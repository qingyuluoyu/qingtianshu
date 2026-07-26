-- Expand-only migration. Phone is account contact data; it is never an auth credential.
ALTER TABLE users ADD COLUMN phone_e164 TEXT;
ALTER TABLE users ADD COLUMN phone_verification_status TEXT NOT NULL DEFAULT 'not_collected'
    CHECK(phone_verification_status IN ('not_collected', 'unverified', 'verified'));
ALTER TABLE users ADD COLUMN phone_verified_at TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_e164_unique
    ON users(phone_e164) WHERE phone_e164 IS NOT NULL;

CREATE TABLE IF NOT EXISTS payment_orders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK(provider IN ('alipay')),
    product_code TEXT NOT NULL,
    phone_e164 TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft', 'cancelled', 'expired')),
    payment_enabled INTEGER NOT NULL DEFAULT 0 CHECK(payment_enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    cancelled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_payment_orders_user_created
    ON payment_orders(user_id, created_at DESC);
