# API and dashboard

Backend: FastAPI (`make api`, listens on 127.0.0.1:8000). Frontend: Next.js (`dashboard/`).

## Data flow
feeds -> recorder -> PostgreSQL -> API poller (1s) -> PriceBoard -> /api/stream (SSE) -> browser
Positions, profit, trades and reconciliation call the SAME tools as the assistant, so the
dashboard and the assistant can never disagree on a number.

## Endpoints (all GET unless noted; JSON; money as exact text)
/api/health (no token) · /api/config · /api/market · /api/stream (SSE) · /api/positions ·
/api/pnl · /api/realized?start&end · /api/trades?limit · /api/recon?exchange&statement&start&end ·
/api/announcements?limit&important_only · POST /api/chat

## Safe defaults
- Chat is OFF unless API_ENABLE_CHAT=true (and a key and model are set).
- Optional bearer token (API_TOKEN). Constant-time comparison. /api/health stays open.
- No CORS, no /docs, no OpenAPI. The browser only talks to the Next.js server.
- Chat: 500 characters, 10 questions per minute, 2 at once, errors without details.
- At most 50 live streams. Tool bugs are logged in full and returned as a plain 500.

## The Next.js proxy (dashboard/src/app/api/[...path]/route.ts)
Forwards /api/<simple-words> to BACKEND_URL and adds the token on the SERVER. The token and
the backend address never reach the browser. Path segments must match [A-Za-z0-9_-]+, so
"..", slashes and encoded tricks are refused. Request bodies over 4 KB are refused.

## Dashboard rules
- Money is text and is formatted with string operations only, never floats.
- Unknown is a dash, never zero. Stale prices are marked.
- Links from announcements are clickable only if they are plain http(s).

## Running a public read-only demo
Keep the API on 127.0.0.1, expose only the Next.js server, leave chat off, set API_TOKEN anyway.
Everything shown is paper data.

## Limits
- Prices reach the screen 1 to 3 seconds after the exchange (recorder flush + 1s poll).
  Redis Streams will shorten this.
- The API process must run with the database up; /api/health reports a dead poller or database.
- The announcements tool for the assistant is not added yet.