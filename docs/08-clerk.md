# The robot clerk (announcement monitor)

Watches announcement pages in a headless browser, classifies titles, and alerts once per
important announcement (Telegram, Slack or console).

## Flow
fetch (Playwright) -> parse (CSS selectors) -> classify -> save -> alert pending -> mark alerted

## Rules
- Sources live in config/announcement_sources.yaml (URL + CSS selectors). Check each site's
  terms and robots.txt first; prefer an official API/RSS. Default poll: every 5 minutes.
- Importance: maintenance always; delistings and listings only if a watched asset (BTC, ETH
  by default) is mentioned. Everything is stored; only important items alert.
- A source's first successful read is a BASELINE: stored, no alerts.
- Layout change = error: a selector that matches nothing raises "layout changed".
- Save first, alert second: a failed alert stays pending and is retried, never duplicated.
- 3 failures in a row for a source: one "failing" alert, then one "recovered" alert.
- Page titles are untrusted: alerts are plain text (Slack escaped), cleaned and truncated.
- Secrets (bot token, webhook URL) never appear in error messages or logs.
- Multiple alert channels: delivery fails only if ALL fail (a partly failed send is logged).

## Tests
Parsing and classification use saved HTML. The browser tests use a local server and are
skipped if Chromium is not installed. No test touches a real site.

## Limits
- Whole-word asset matching: "BTCUSDT" does not match "BTC".
- Keyword rules, not understanding: unusual wording can be missed. Everything is stored, so
  misses can be reviewed.
- Database outages stop the loop (restart it with a process supervisor).
- Sites with anti-bot protection may block a headless browser. Do not try to evade it.