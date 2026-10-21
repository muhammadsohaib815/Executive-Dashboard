# Project structure

The repository is organized by responsibility so application code, database assets, frontend assets, images, and documentation are easy to locate.

```text
Executive Dashboard/
|-- .env                         # Local database and runtime settings
|-- assets/
|   `-- images/                  # Logos and dashboard images
|-- db/
|   |-- migrations/              # SQL migrations and rollback plans
|   `-- *.sql                    # Database rollups, triggers, and procedures
|-- docs/                        # Markdown documentation
|-- frontend/
|   |-- html/                    # HTML entry pages
|   |-- css/                     # Stylesheets
|   `-- js/                      # Browser JavaScript modules
`-- scripts/
    |-- server.py                # FastAPI application entry point
    |-- performance_monitor.py   # Query timing and pool metrics
    |-- response_cache.py        # Response cache implementation
    |-- db/                      # Python database maintenance commands
    `-- services/ai_analysis/    # AI analysis and evidence services
```

## Run the dashboard

From the repository root:

```powershell
python scripts/server.py
```

Open `http://localhost:8000`. The backend serves `frontend/html/index.html`, mounts styles at `/css`, browser scripts at `/js`, and images at `/images`.

## Run database commands

Database Python commands are modules under `scripts.db`, while SQL remains under `db`:

```powershell
python -m scripts.db.install_call_data_rollup
python -m scripts.db.refresh_sales_monthly_summaries --dirty --expect-db <database-name> --apply
python -m scripts.db.validate_sales_monthly_summaries --expect-db <database-name>
```

Runtime Python code is kept under `scripts` and is separate from the browser assets under `frontend`.
