-- Precomputed FMCG call activity for the dashboard. Run after loading call_data.
-- The four grains preserve exact distinct call-day counts under any staff scope.
CREATE TABLE IF NOT EXISTS call_data_rollup (
    kind text NOT NULL CHECK (kind IN ('manager_day', 'shop_month', 'shop_day', 'outcome')),
    month text NOT NULL,
    position_code text NOT NULL,
    manager text,
    ff_name text,
    customer_name text,
    call_date text,
    calls bigint NOT NULL DEFAULT 0,
    accepted bigint NOT NULL DEFAULT 0,
    rejected bigint NOT NULL DEFAULT 0,
    shop_closed bigint NOT NULL DEFAULT 0
);

-- Older generic indexes held every nullable dimension for every row. Replace
-- them with compact, exact keys tailored to each grain.
DROP INDEX IF EXISTS idx_call_rollup_key;
DROP INDEX IF EXISTS idx_call_rollup_manager;
DROP INDEX IF EXISTS idx_call_rollup_shop_month;
DROP INDEX IF EXISTS idx_call_rollup_shop_day;
DROP INDEX IF EXISTS idx_call_rollup_outcome;
CREATE UNIQUE INDEX IF NOT EXISTS uq_call_rollup_manager
    ON call_data_rollup (month, position_code, manager, ff_name, call_date)
    NULLS NOT DISTINCT
    WHERE kind = 'manager_day';
CREATE UNIQUE INDEX IF NOT EXISTS uq_call_rollup_shop_month
    ON call_data_rollup (month, position_code, customer_name)
    INCLUDE (calls) NULLS NOT DISTINCT WHERE kind = 'shop_month';
CREATE UNIQUE INDEX IF NOT EXISTS uq_call_rollup_shop_day
    ON call_data_rollup (month, customer_name, position_code, call_date)
    NULLS NOT DISTINCT
    WHERE kind = 'shop_day';
CREATE UNIQUE INDEX IF NOT EXISTS uq_call_rollup_outcome
    ON call_data_rollup (month, position_code)
    INCLUDE (calls, accepted, rejected, shop_closed) NULLS NOT DISTINCT
    WHERE kind = 'outcome';

CREATE OR REPLACE PROCEDURE refresh_call_data_rollup()
LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE call_data_rollup;

    INSERT INTO call_data_rollup (kind, month, position_code, manager, ff_name, call_date, calls)
    SELECT 'manager_day', month, position_code, manager, ff_name, call_date, COUNT(*)
    FROM call_data
    WHERE UPPER(COALESCE(team, '')) LIKE 'FMCG%'
      AND month IS NOT NULL AND position_code IS NOT NULL
    GROUP BY month, position_code, manager, ff_name, call_date;

    INSERT INTO call_data_rollup (kind, month, position_code, customer_name, calls)
    SELECT 'shop_month', month, position_code, customer_name, COUNT(*)
    FROM call_data
    WHERE UPPER(COALESCE(team, '')) LIKE 'FMCG%'
      AND month IS NOT NULL AND position_code IS NOT NULL
    GROUP BY month, position_code, customer_name;

    INSERT INTO call_data_rollup (kind, month, position_code, customer_name, call_date, calls)
    SELECT 'shop_day', month, position_code, customer_name, call_date, COUNT(*)
    FROM call_data
    WHERE UPPER(COALESCE(team, '')) LIKE 'FMCG%'
      AND month IS NOT NULL AND position_code IS NOT NULL
    GROUP BY month, position_code, customer_name, call_date;

    INSERT INTO call_data_rollup (kind, month, position_code, calls, accepted, rejected, shop_closed)
    SELECT 'outcome', month, position_code, COUNT(*),
           COUNT(*) FILTER (WHERE UPPER(TRIM(COALESCE("order", ''))) = 'ACCEPTED'),
           COUNT(*) FILTER (WHERE UPPER(TRIM(COALESCE("order", ''))) = 'REJECTED'),
           COUNT(*) FILTER (WHERE UPPER(TRIM(COALESCE("order", ''))) = 'SHOPCLOSED')
    FROM call_data
    WHERE UPPER(COALESCE(team, '')) LIKE 'FMCG%'
      AND month IS NOT NULL AND position_code IS NOT NULL
    GROUP BY month, position_code;

    ANALYZE call_data_rollup;
END;
$$;
