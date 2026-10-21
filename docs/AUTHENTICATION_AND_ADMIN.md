# Authentication and administration

The dashboard now supports session-based login and role-based access.

## Roles

| Role | Dashboard | Administration | Data import |
|---|---|---|---|
| `admin` | Yes | Yes | Yes |
| `manager` | Yes | No | No |
| `executive` | Yes | No | No |
| `viewer` | Yes | No | No |

Passwords are hashed with PBKDF2-HMAC-SHA256. The browser receives an HTTP-only, signed session cookie; passwords are never stored in the browser or returned by the API.

## First login

1. Install the schema once with `python scripts/db/install_dashboard_auth.py`.
2. Start the server with `python scripts/server.py`.
3. Open `http://localhost:8000/`.
4. Choose **First-time administrator setup**.
5. Create the first administrator account.

The setup endpoint is disabled automatically after the first account exists. The SQL is also available as `db/migrations/006_dashboard_auth.sql` for managed migration runners.

## Administration panel

An administrator can open `/admin` to:

- Create users and assign `admin`, `manager`, `executive`, or `viewer` roles.
- Activate or deactivate accounts.
- Import JSON rows into the allow-listed sales, target, staff, FMCG call, FMCG exception, Pharma provider-call, or legacy call tables.

The import endpoint validates table names and column names against PostgreSQL metadata and uses parameterized inserts. It does not accept SQL statements.

## Production settings

Set a stable, private `AUTH_SECRET` in `.env` so sessions survive restarts. Set `AUTH_COOKIE_SECURE=true` when serving through HTTPS. The default session lifetime is 8 hours and can be changed with `AUTH_SESSION_TTL_SECONDS`.
