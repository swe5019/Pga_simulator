-- Already applied to the live database. Kept here so the schema is in version
-- control and can be recreated.
CREATE TABLE IF NOT EXISTS leads (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  email      TEXT NOT NULL,
  email_key  TEXT NOT NULL UNIQUE,   -- lower-cased, for one row per address
  source     TEXT NOT NULL DEFAULT 'unknown',
  first_seen TEXT NOT NULL,
  last_seen  TEXT NOT NULL,
  hits       INTEGER NOT NULL DEFAULT 1,
  referrer   TEXT,
  ua         TEXT,
  country    TEXT
);
CREATE INDEX IF NOT EXISTS leads_first_seen ON leads(first_seen);
CREATE INDEX IF NOT EXISTS leads_source ON leads(source);

-- Per-hour write budget per IP.
CREATE TABLE IF NOT EXISTS rate (
  ip     TEXT PRIMARY KEY,
  window TEXT NOT NULL,
  n      INTEGER NOT NULL DEFAULT 1
);
