/* ═══════════════════════════════════════════════════════════
   Личный кабинет.

   Кабинет и барометр разделены намеренно: витрина статическая и работает,
   даже когда Worker лежит. Поэтому здесь ни одна ошибка сети не должна
   выглядеть как ошибка пользователя — если служба входа молчит, так и
   написано, а не «неверный адрес».
   ═══════════════════════════════════════════════════════════ */

const API = '/api';
const $ = s => document.querySelector(s);

function show(which) {
  ['signin', 'cabinet', 'loading', 'offline'].forEach(id => {
    const n = document.getElementById(id);
    if (n) n.hidden = id !== which;
  });
}

const PLAN_NAME = { free: 'Бесплатный', pro: 'Pro', trial: 'Пробный' };

function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(String(s).replace(' ', 'T'));
  if (isNaN(d)) return String(s);
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(d);
}

async function whoAmI() {
  // credentials: same-origin — сессия лежит в куке, которую ставит Worker.
  const r = await fetch(`${API}/me`, { credentials: 'same-origin', cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

function paintCabinet(me) {
  $('#accEmail').textContent = me.email || '—';
  $('#accPlan').textContent = PLAN_NAME[me.plan] || me.plan || '—';
  $('#accUntil').textContent = me.active ? fmtDate(me.current_period_end) : 'нет активной подписки';
  $('#accFine').textContent = me.active
    ? 'Подписка активна. Продление и отмена — на стороне платёжной системы.'
    : 'Открытая часть барометра доступна без подписки и остаётся бесплатной.';
  show('cabinet');
}

async function boot() {
  try {
    const me = await whoAmI();
    if (me && me.email) paintCabinet(me);
    else show('signin');
  } catch (e) {
    // Отличаем «не вошёл» от «служба недоступна»: первое нормально,
    // второе — повод сказать правду, а не показывать форму молча.
    console.error('кабинет:', e);
    show('offline');
  }
}

$('#loginForm')?.addEventListener('submit', async ev => {
  ev.preventDefault();
  const email = $('#email').value.trim();
  const btn = $('#loginBtn'), msg = $('#loginMsg');
  btn.disabled = true;
  btn.textContent = 'Отправляем…';
  try {
    await fetch(`${API}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ email }),
    });
    // Ответ одинаков для существующего и несуществующего адреса — так форма
    // входа не превращается в способ проверять, кто у нас зарегистрирован.
    // Значит и сообщение обязано быть одинаковым.
    msg.hidden = false;
    msg.textContent = 'Если адрес верный, письмо со ссылкой уже отправлено. Проверьте почту, в том числе папку со спамом.';
    btn.textContent = 'Отправлено';
  } catch (e) {
    msg.hidden = false;
    msg.textContent = 'Служба входа не ответила. Попробуйте позже — барометр работает и без неё.';
    btn.disabled = false;
    btn.textContent = 'Прислать ссылку';
  }
});

$('#logoutBtn')?.addEventListener('click', async () => {
  try {
    await fetch(`${API}/logout`, { method: 'POST', credentials: 'same-origin' });
  } catch (e) { /* выходим в любом случае: кука всё равно станет негодной */ }
  show('signin');
});

show('loading');
boot();
