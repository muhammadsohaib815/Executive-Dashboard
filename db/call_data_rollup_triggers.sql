-- Keep the rollup current as call_data changes. Statement triggers aggregate
-- a bulk load once, rather than doing four index updates per imported row.
CREATE INDEX IF NOT EXISTS idx_call_rollup_empty
    ON call_data_rollup (kind) WHERE calls <= 0;

CREATE OR REPLACE FUNCTION sync_call_data_rollup()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    pass integer;
    source_table text;
    delta integer;
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        TRUNCATE call_data_rollup;
        RETURN NULL;
    END IF;

    FOR pass IN 1..(CASE WHEN TG_OP = 'UPDATE' THEN 2 ELSE 1 END) LOOP
        IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND pass = 1) THEN
            source_table := 'old_rows';
            delta := -1;
        ELSE
            source_table := 'new_rows';
            delta := 1;
        END IF;

        EXECUTE format($sql$
            INSERT INTO call_data_rollup
                (kind, month, position_code, manager, ff_name, call_date, calls)
            SELECT 'manager_day', month, position_code, manager, ff_name, call_date,
                   COUNT(*) * $1
            FROM %I
            WHERE UPPER(COALESCE(team, '')) LIKE 'FMCG%%'
              AND month IS NOT NULL AND position_code IS NOT NULL
            GROUP BY month, position_code, manager, ff_name, call_date
            ON CONFLICT (month, position_code, manager, ff_name, call_date)
            WHERE kind = 'manager_day'
            DO UPDATE SET calls = call_data_rollup.calls + EXCLUDED.calls
        $sql$, source_table) USING delta;

        EXECUTE format($sql$
            INSERT INTO call_data_rollup
                (kind, month, position_code, customer_name, calls)
            SELECT 'shop_month', month, position_code, customer_name, COUNT(*) * $1
            FROM %I
            WHERE UPPER(COALESCE(team, '')) LIKE 'FMCG%%'
              AND month IS NOT NULL AND position_code IS NOT NULL
            GROUP BY month, position_code, customer_name
            ON CONFLICT (month, position_code, customer_name)
            WHERE kind = 'shop_month'
            DO UPDATE SET calls = call_data_rollup.calls + EXCLUDED.calls
        $sql$, source_table) USING delta;

        EXECUTE format($sql$
            INSERT INTO call_data_rollup
                (kind, month, position_code, customer_name, call_date, calls)
            SELECT 'shop_day', month, position_code, customer_name, call_date,
                   COUNT(*) * $1
            FROM %I
            WHERE UPPER(COALESCE(team, '')) LIKE 'FMCG%%'
              AND month IS NOT NULL AND position_code IS NOT NULL
            GROUP BY month, position_code, customer_name, call_date
            ON CONFLICT (month, customer_name, position_code, call_date)
            WHERE kind = 'shop_day'
            DO UPDATE SET calls = call_data_rollup.calls + EXCLUDED.calls
        $sql$, source_table) USING delta;

        EXECUTE format($sql$
            INSERT INTO call_data_rollup
                (kind, month, position_code, calls, accepted, rejected, shop_closed)
            SELECT 'outcome', month, position_code, COUNT(*) * $1,
                   COUNT(*) FILTER (WHERE UPPER(TRIM(COALESCE("order", ''))) = 'ACCEPTED') * $1,
                   COUNT(*) FILTER (WHERE UPPER(TRIM(COALESCE("order", ''))) = 'REJECTED') * $1,
                   COUNT(*) FILTER (WHERE UPPER(TRIM(COALESCE("order", ''))) = 'SHOPCLOSED') * $1
            FROM %I
            WHERE UPPER(COALESCE(team, '')) LIKE 'FMCG%%'
              AND month IS NOT NULL AND position_code IS NOT NULL
            GROUP BY month, position_code
            ON CONFLICT (month, position_code)
            WHERE kind = 'outcome'
            DO UPDATE SET calls = call_data_rollup.calls + EXCLUDED.calls,
                          accepted = call_data_rollup.accepted + EXCLUDED.accepted,
                          rejected = call_data_rollup.rejected + EXCLUDED.rejected,
                          shop_closed = call_data_rollup.shop_closed + EXCLUDED.shop_closed
        $sql$, source_table) USING delta;

        IF delta = -1 THEN
            DELETE FROM call_data_rollup WHERE calls <= 0;
        END IF;
    END LOOP;

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_call_rollup_insert ON call_data;
CREATE TRIGGER trg_call_rollup_insert AFTER INSERT ON call_data
    REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT
    EXECUTE FUNCTION sync_call_data_rollup();

DROP TRIGGER IF EXISTS trg_call_rollup_update ON call_data;
CREATE TRIGGER trg_call_rollup_update AFTER UPDATE ON call_data
    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
    EXECUTE FUNCTION sync_call_data_rollup();

DROP TRIGGER IF EXISTS trg_call_rollup_delete ON call_data;
CREATE TRIGGER trg_call_rollup_delete AFTER DELETE ON call_data
    REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT
    EXECUTE FUNCTION sync_call_data_rollup();

DROP TRIGGER IF EXISTS trg_call_rollup_truncate ON call_data;
CREATE TRIGGER trg_call_rollup_truncate AFTER TRUNCATE ON call_data
    FOR EACH STATEMENT EXECUTE FUNCTION sync_call_data_rollup();
