-- Expand-only portfolio ledger contract. Existing position and trade rows
-- remain readable and receive conservative defaults.
ALTER TABLE positions
    ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE positions
    ADD COLUMN method_version TEXT NOT NULL DEFAULT 'moving_weighted_average_v1';

ALTER TABLE trades
    ADD COLUMN idempotency_key TEXT;

ALTER TABLE trades
    ADD COLUMN request_fingerprint TEXT;

ALTER TABLE trades
    ADD COLUMN position_closed INTEGER NOT NULL DEFAULT 0
        CHECK(position_closed IN (0, 1));

CREATE UNIQUE INDEX uq_trades_user_idempotency
    ON trades(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX idx_trades_position_executed
    ON trades(position_id, executed_at ASC);
