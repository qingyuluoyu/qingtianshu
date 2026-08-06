# Environment

## Git
- HEAD: d0a9b9b75200d4b89452c803a14bcc1add136481
- Branch: codex/structured-ai-writeback
- Working tree: clean (no uncommitted changes)

## Runtime
- Python: 3.12.10
- uv: 0.8.24
- Node.js: v24.18.0
- npm: 11.16.0

## Database
- Host: 127.0.0.1
- Port: 5432
- Database: qingshu
- Environment: LOCAL DEVELOPMENT
- PostgreSQL version: 17.10 (Windows)
- Connection: Local only (not production)

## Server
- Bind: 127.0.0.1:8002 (for contract collection)
- Default port: 8001 (from .env)
- Start command: `uv run qingshu-start` or `uv run app.cli:main`
- Uvicorn: app.main:app

## Security
- Database password: NOT OUTPUT (in .env)
- API keys: NOT OUTPUT (in .env)
- Session cookie: HttpOnly, Secure, SameSite=strict
- No secrets in collected contracts

## Verification
- PostgreSQL listening on 127.0.0.1:5432
- Database name: qingshu (local)
- 80 public tables
- Connection verified: OK
