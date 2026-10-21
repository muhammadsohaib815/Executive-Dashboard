# Call data rollup

Dashboard index migrations are documented in [INDEX_OPTIMIZATION.md](INDEX_OPTIMIZATION.md).
Monthly sales summary installation, refresh, validation, and recovery are
documented in [SALES_MONTHLY_SUMMARIES.md](SALES_MONTHLY_SUMMARIES.md).
Connection-pool sizing, timeout settings, monitoring, and post-import database
maintenance are documented in [CONNECTION_POOL_AND_MAINTENANCE.md](CONNECTION_POOL_AND_MAINTENANCE.md).
The measured partitioning decision and guarded future migration plan are in
[PARTITIONING_EVALUATION.md](PARTITIONING_EVALUATION.md).

The current Call Performance panel reads `fmcg_cust_call`, `fmcg_exception`,
and `pharma_provider_calls`. It maps each source `ff_id` to
`staff_master.hawk_emp_id`, then applies the selected hierarchy and month.

`call_data_rollup` retains the older FMCG activity model at four grains:
manager/day, shop/month, shop/day, and outcome/position/month. Keep it only for
legacy reports that still read `call_data`.

Install or rebuild the table from the project root:

```text
python -m scripts.db.install_call_data_rollup
```

The installer holds call-data writes while it rebuilds the table and installs
triggers in one transaction. Existing inserts, updates, deletes, and truncates
then keep the rollup current automatically. If an import **drops and recreates**
`call_data`, run the installer again because PostgreSQL drops its triggers with
the table. For a manual rebuild after a data repair that preserves the table,
run `CALL refresh_call_data_rollup();` in PostgreSQL.
