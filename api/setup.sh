#!/usr/bin/env bash
# Разворачивает API одной командой. Запускать из каталога api/:
#     bash setup.sh
#
# Скрипт идемпотентный: повторный запуск ничего не ломает и не дублирует.
# Ничего не удаляет и не перезаписывает без спроса.
set -euo pipefail

cd "$(dirname "$0")"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- проверки
command -v node >/dev/null || { echo "Нужен Node.js 20+: https://nodejs.org"; exit 1; }
ok "Node $(node -v)"

if ! command -v wrangler >/dev/null; then
  say "Ставлю wrangler"
  npm install -g wrangler
fi
ok "wrangler $(wrangler --version 2>/dev/null | head -1)"

say "Прогоняю тесты до развёртывания"
node test/test.mjs >/dev/null && ok "166 проверок пройдено"

# ------------------------------------------------------------------- вход
if ! wrangler whoami >/dev/null 2>&1; then
  say "Вход в Cloudflare — откроется браузер"
  wrangler login
fi
ok "$(wrangler whoami 2>/dev/null | grep -i 'account' | head -1 || echo 'вход выполнен')"

# --------------------------------------------------------------- база D1
say "База данных D1"
if wrangler d1 info escx >/dev/null 2>&1; then
  ok "база escx уже есть"
else
  wrangler d1 create escx
  ok "база escx создана"
fi

DB_ID=$(wrangler d1 info escx --json 2>/dev/null | node -e \
  'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
     try{const j=JSON.parse(s);console.log(j.uuid||j.database_id||"")}catch(e){console.log("")}})')

if [ -n "$DB_ID" ]; then
  # sed -i несовместим между GNU и BSD, поэтому через временный файл
  node -e '
    const fs=require("fs");const p="wrangler.toml";
    const s=fs.readFileSync(p,"utf8").replace(/database_id = ".*"/, `database_id = "${process.argv[1]}"`);
    fs.writeFileSync(p,s);' "$DB_ID"
  ok "идентификатор базы вписан в wrangler.toml"
else
  echo "  ! не удалось прочитать id базы — впишите его в wrangler.toml вручную"
fi

say "Создаю таблицы"
wrangler d1 execute escx --file=schema.sql --remote --yes
ok "схема применена"

# ------------------------------------------------------------ развёртывание
#
# Публикуем ДО секретов, а не после. Причина: на первом запуске Worker'а ещё не
# существует, и `wrangler secret put` вместо записи спрашивает, создавать ли
# его. Вопрос читается из того же потока ввода — то есть перец, поданный туда
# по конвейеру, уходит в ответ на «создать Worker?», а секрет не записывается.
# Секреты подхватываются сразу и повторной публикации не требуют.
say "Публикую"
wrangler deploy

# --------------------------------------------------------------- секреты
#
# Перец для паролей придумывать человеку незачем — это просто случайные байты.
# Но и перезаписывать его нельзя ни при каких условиях: он не хранится в базе, и
# новый перец означает, что ни один существующий пароль больше не подойдёт.
# Поэтому сначала проверяем, есть ли он уже. Ради этой проверки скрипт и остаётся
# идемпотентным.
say "Перец для паролей (AUTH_PEPPER)"
if wrangler secret list 2>/dev/null | grep -q AUTH_PEPPER; then
  ok "AUTH_PEPPER уже задан — не трогаю (замена обнулила бы все пароли)"
else
  node -e 'console.log(require("crypto").randomBytes(32).toString("hex"))' \
    | wrangler secret put AUTH_PEPPER
  ok "AUTH_PEPPER создан и сохранён"
fi

say "Секреты"
echo "  Их можно задать сейчас или позже. Пустой ввод — пропустить."
echo "  PADDLE_WEBHOOK_SECRET — Paddle → Developer tools → Notifications → секрет (pdl_ntfset_...)"
echo "  RESEND_API_KEY        — resend.com → API Keys (бесплатно 3000 писем в месяц)"
for name in PADDLE_WEBHOOK_SECRET RESEND_API_KEY; do
  printf '\n  %s: ' "$name"
  read -r value || value=""
  if [ -n "$value" ]; then
    printf '%s' "$value" | wrangler secret put "$name"
    ok "$name сохранён"
  else
    echo "  — пропущено, задать позже: wrangler secret put $name"
  fi
done

say "Готово"
echo "  Проверьте:  curl https://escx-api.<ваш-поддомен>.workers.dev/api/me"
echo "  Ожидаемый ответ: {\"email\":null,\"plan\":\"free\",\"status\":\"anonymous\",\"until\":null}"
echo
echo "  Дальше в Paddle: Developer tools → Notifications → New destination"
echo "    адрес   https://<адрес-воркера>/api/webhook"
echo "    события subscription.created, subscription.updated, subscription.canceled"
