# Project structure

The repository is organized by responsibility so that application code, database assets, frontend assets, images, documentation, and tests are easy to locate.

```text
Executive Dashboard/
├── .env                         # Local database and runtime settings
├── assets/
│   └── images/                  # Logos and reference/dashboard images
├── db/
│   ├── migrations/              # SQL migrations and rollback plans
│   └── *.sql                    # Database rollups, triggers, and procedures
├── docs/                        # All Markdown documentation
├── frontend/
│   ├── html/                    # HTML entry pages
│   ├── css/                     # Stylesheets
│   └── js/                      # Browser JavaScript modules
├── scripts/
│   ├── server.py                # FastAPI application entry point
│   ├── performance_monitor.py   # Query timing and pool metrics
│   ├── response_cache.py        # Response cache implementation
│   ├── db/                      # Python database maintenance commands
│   └── services/ai_analysis/    # AI analysis and evidence services
├── tests/                       # Automated Python and JavaScript tests
└── pytest.ini                   # Test import configuration
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

## Run checks

```powershell
pytest -q
node tests/test_ai_frontend.cjs
node tests/test_territory_frontend.cjs
```

Runtime Python code is kept under `scripts`; tests remain under `tests` so test discovery and test-only dependencies stay separate from production code.
