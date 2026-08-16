-- D1 — это SQLite. Тот же движок, что в пайплайне сбора данных:
-- ни новой технологии, ни нового языка запросов учить не нужно.

CREATE TABLE IF NOT EXISTS subscriptions (
  email              TEXT NOT NULL,
  provider           TEXT NOT NULL,
  subscription_id    TEXT,
  customer_id        TEXT,
  price_id           TEXT,
  plan               TEXT NOT NULL DEFAULT 'pro',
  status             TEXT NOT NULL,
  active             INTEGER NOT NULL DEFAULT 0,
  current_period_end TEXT,
  updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (provider, subscription_id)
);
CREATE INDEX IF NOT EXISTS ix_sub_email ON subscriptions(email, updated_at DESC);

-- Журнал вебхуков. Нужен по двум причинам:
-- платёжка присылает событие повторно при сбое сети (защита от двойной обработки),
-- и при споре о деньгах нужно показать, что именно пришло.
CREATE TABLE IF NOT EXISTS webhook_log (
  event_id   TEXT PRIMARY KEY,
  provider   TEXT NOT NULL,
  event_type TEXT,
  received_at TEXT NOT NULL DEFAULT (datetime('now')),
  payload    TEXT
);

CREATE TABLE IF NOT EXISTS magic_links (
  token_hash TEXT PRIMARY KEY,
  email      TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  used       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_magic_exp ON magic_links(expires_at);

CREATE TABLE IF NOT EXISTS sessions (
  session_hash TEXT PRIMARY KEY,
  email        TEXT NOT NULL,
  expires_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sess_exp ON sessions(expires_at);
