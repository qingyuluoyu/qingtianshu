# Routing and Proxy Map

## Current Page Routes

| Route | Handler | Returns |
|-------|---------|---------|
| / | RedirectResponse | 302 to /today |
| /today | HTML page | today.html |
| /watchlist | HTML page | watchlist.html |
| /research | HTML page | research.html |
| /research/{{id}} | HTML page | research.html (SPA) |
| /reviews | HTML page | reviews.html |
| /stocks/{{symbol}} | HTML page | stock.html (SPA) |
| /advisor-lab | HTML page | advisor-lab.html |
| /static/* | StaticFile | Static assets |

## API Path Prefixes

Frontend Vite dev proxy must forward these prefixes to FastAPI:

- /v1
- /me
- /markets
- /indices
- /sectors
- /stocks
- /a-share
- /research-reports
- /system
- /events
- /session
- /sessions
- /users
- /fund-products

## Conflict Avoidance

### Vite SPA Fallback vs API
- Vite must NOT fallback API paths to index.html
- Use regex or exact path matching in proxy config

### /stocks/:symbol vs /stocks/{{symbol}}/history
- Page route: /stocks/{{symbol}} (exact match or SPA)
- API route: /stocks/{{symbol}}/history (longer path)
- Proxy must match longer path first

### /research vs /research-reports
- /research is a page route (HTML)
- /research-reports is an API prefix (JSON)
- No conflict, but Vite must proxy /research-reports/*

### SSE Paths
- /events must NOT be caught by SPA fallback
- /me/chat/stream/* must NOT be caught by SPA fallback
- Use exact match or regex in proxy

## Production (Temporary)
- Do nothing for now
- Will be handled when deploying
