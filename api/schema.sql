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

-- Пользователи. Ключ — адрес почты, а не выдуманный внутренний id: подписка
-- приходит из платёжки тоже с адресом, и лишний слой сопоставления был бы
-- ещё одним местом, где они разъезжаются.
--
-- pass_hash допускает NULL намеренно. Аккаунт без пароля — это будущий вход
-- через Google: личность привязана к адресу, а не к способу входа, поэтому
-- добавление второго способа не потребует переделки таблицы.
--
-- verified_at ставится, когда человек перешёл по ссылке из письма. Вход им НЕ
-- ограничен: почта пока не заведена, и требование подтверждения закрыло бы
-- кабинет насовсем. Как только отправка писем заработает, флаг
-- REQUIRE_VERIFIED_EMAIL включает проверку для платных возможностей.
--
-- notify — согласие на уведомления. Хранится отдельно от факта регистрации,
-- потому что отказ от рассылки не должен означать удаление аккаунта.
CREATE TABLE IF NOT EXISTS users (
  email        TEXT PRIMARY KEY,
  pass_hash    TEXT,
  verified_at  TEXT,
  notify       INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Одноразовые ссылки из письма. Раньше это был вход, теперь — восстановление
-- пароля и подтверждение адреса. Токен лежит только в виде SHA-256:
-- дамп базы не должен давать вход.
CREATE TABLE IF NOT EXISTS magic_links (
  token_hash TEXT PRIMARY KEY,
  email      TEXT NOT NULL,
  purpose    TEXT NOT NULL DEFAULT 'reset',   -- reset | verify
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
CREATE INDEX IF NOT EXISTS ix_sess_email ON sessions(email);

-- Счётчик неудачных попыток входа.
--
-- Окно истекает само и запись обнуляется — это НЕ блокировка аккаунта.
-- Блокировка выглядит логичнее, но её легко обратить против пользователя:
-- зная адрес, посторонний навсегда закрывает человеку вход, просто ошибаясь
-- паролем. Здесь худшее, чего он добьётся, — пауза до конца окна.
--
-- scope — 'email:<адрес>' или 'ip:<адрес>'. Считаем по обоим: перебор одного
-- пароля по многим адресам счётчик по адресу не поймает.
CREATE TABLE IF NOT EXISTS login_fails (
  scope      TEXT PRIMARY KEY,
  fails      INTEGER NOT NULL DEFAULT 0,
  window_end INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fails_window ON login_fails(window_end);
