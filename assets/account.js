/* ═══════════════════════════════════════════════════════════
   Личный кабинет. Вход по адресу почты и паролю.

   Кабинет и барометр разделены намеренно: витрина статическая и работает,
   даже когда Worker лежит. Поэтому здесь ни одна ошибка сети не должна
   выглядеть как ошибка пользователя — если служба входа молчит, так и
   написано, а не «неверный адрес».

   Второе правило, из-за которого код выглядит так: текст отказа при входе
   берётся с сервера как есть и НЕ уточняется на клиенте. Сервер отвечает
   одинаково на неверный пароль и на незнакомый адрес; если здесь дописать
   «проверьте, зарегистрированы ли вы», вся эта осторожность пропадёт зря.
   ═══════════════════════════════════════════════════════════ */

const API = '/api';
const $ = s => document.querySelector(s);
const SCREENS = ['auth', 'pending', 'forgot', 'reset', 'cabinet', 'loading', 'offline'];

/* Адрес и пароль последней попытки. Нужны ровно для одной кнопки — «выслать
 * письмо ещё раз»: ручка требует пароль, чтобы посторонний не мог засыпать
 * чужой ящик нашими письмами. Живут только в памяти вкладки и стираются, как
 * только пригодились; ни в хранилище, ни в адресную строку не попадают. */
let lastCreds = null;

function show(which) {
  SCREENS.forEach(id => {
    const n = document.getElementById(id);
    if (n) n.hidden = id !== which;
  });
}

function say(node, text, bad = false) {
  node.hidden = false;
  node.textContent = text;
  node.classList.toggle('acc__msg--bad', bad);
}

const PLAN_NAME = { free: 'Бесплатный', pro: 'Pro', team: 'Team', api: 'API', trial: 'Пробный' };

function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(String(s).replace(' ', 'T'));
  if (isNaN(d)) return String(s);
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(d);
}

/**
 * Запрос к API.
 *
 * Различает три исхода, которые нельзя путать: получилось, сервер отказал
 * (и объяснил почему), сети нет вовсе. Третий случай — не вина человека,
 * и сообщение о нём должно быть другим.
 */
async function call(path, body) {
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      cache: 'no-store',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw Object.assign(new Error('нет связи'), { offline: true });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || `ошибка ${res.status}`), { data });
  return data;
}

const NET_DOWN = 'Служба входа не ответила. Попробуйте позже — барометр работает и без неё.';

/* ------------------------------------------------------- вход и регистрация */

let mode = 'signin';   // signin | register

function setMode(next) {
  mode = next;
  const reg = mode === 'register';
  $('#authTitle').textContent = reg ? 'Регистрация' : 'Вход';
  $('#authLede').textContent = reg
    ? 'Адрес почты и пароль. На этот адрес мы пришлём подтверждение и уведомления, если вы их включите.'
    : 'Адрес почты и пароль. Тот же адрес получит уведомления, если вы их включите.';
  $('#authBtn').textContent = reg ? 'Зарегистрироваться' : 'Войти';
  $('#modeBtn').textContent = reg ? 'Уже есть аккаунт — войти' : 'Нет аккаунта — зарегистрироваться';
  // autocomplete подсказывает браузеру, предлагать сохранённый пароль или
  // придумать новый. Без переключения менеджер паролей подставляет старый
  // в поле, где ждут новый.
  $('#password').setAttribute('autocomplete', reg ? 'new-password' : 'current-password');
  $('#authMsg').hidden = true;
  $('#forgotBtn').hidden = reg;
  // Согласие с документами показываем только при регистрации: при входе
  // человек согласился уже тогда, и повторять — лишний шум на экране.
  const consent = $('#authConsent');
  if (consent) consent.hidden = !reg;
}

$('#modeBtn')?.addEventListener('click', () => setMode(mode === 'register' ? 'signin' : 'register'));

$('#forgotBtn')?.addEventListener('click', () => {
  $('#forgotEmail').value = $('#email').value.trim();
  show('forgot');
});

$('#backToAuth')?.addEventListener('click', () => show('auth'));

$('#authForm')?.addEventListener('submit', async ev => {
  ev.preventDefault();
  const email = $('#email').value.trim();
  const password = $('#password').value;
  const btn = $('#authBtn'), msg = $('#authMsg');
  const label = btn.textContent;

  if (password.length < 10 && mode === 'register') {
    say(msg, 'Пароль короче 10 символов.', true);
    return;
  }

  btn.disabled = true;
  btn.textContent = mode === 'register' ? 'Создаём…' : 'Входим…';
  msg.hidden = true;
  try {
    const r = await call(mode === 'register' ? '/register' : '/signin', { email, password });
    $('#password').value = '';
    // Регистрация прошла, но сессии нет: адрес ждёт подтверждения.
    if (r.pending) { toPending(email, password); return; }
    await boot();
  } catch (e) {
    // Пароль верный, но адрес не подтверждён — это не ошибка ввода, и
    // держать человека на форме входа, где он будет пробовать пароль
    // заново, незачем.
    if (e.data?.code === 'unverified') { toPending(email, password); return; }

    say(msg, e.offline ? NET_DOWN : e.message, true);
    // Занятый адрес при регистрации — единственный случай, когда полезно
    // подсказать действие: человек уже зарегистрирован и просто забыл.
    if (e.data?.code === 'taken') setMode('signin');
    btn.disabled = false;
    btn.textContent = label;
  }
});

/* ------------------------------------------------- ожидание подтверждения */

function toPending(email, password) {
  lastCreds = { email, password };
  $('#pendingEmail').textContent = email;
  $('#pendingMsg').hidden = true;
  const btn = $('#authBtn');           // форма входа осталась с «Создаём…»
  btn.disabled = false;
  btn.textContent = mode === 'register' ? 'Зарегистрироваться' : 'Войти';
  show('pending');
}

$('#pendingBack')?.addEventListener('click', () => { setMode('signin'); show('auth'); });

$('#resendBtn')?.addEventListener('click', async () => {
  const btn = $('#resendBtn'), msg = $('#pendingMsg');

  // Страницу перезагрузили — пароль из памяти пропал, а без него ручка письмо
  // не вышлет. Отправляем человека войти: вход снова приведёт сюда же.
  if (!lastCreds) {
    setMode('signin');
    show('auth');
    say($('#authMsg'), 'Введите адрес и пароль ещё раз — после этого сможем выслать письмо повторно.');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Отправляем…';
  try {
    const r = await call('/verify/resend', lastCreds);
    say(msg, r.verified
      ? 'Этот адрес уже подтверждён — можно входить.'
      : 'Письмо отправлено ещё раз. Проверьте почту, в том числе папку со спамом.');
    btn.textContent = 'Отправлено';   // намеренно не включаем обратно
  } catch (e) {
    say(msg, e.offline ? NET_DOWN : e.message, true);
    btn.disabled = false;
    btn.textContent = 'Выслать письмо ещё раз';
  }
});

/* ------------------------------------------------------------ забытый пароль */

$('#forgotForm')?.addEventListener('submit', async ev => {
  ev.preventDefault();
  const btn = $('#forgotSubmit'), msg = $('#forgotMsg');
  btn.disabled = true;
  btn.textContent = 'Отправляем…';
  try {
    await call('/password/forgot', { email: $('#forgotEmail').value.trim() });
    // Ответ сервера одинаков для любого адреса — значит и текст здесь
    // обязан быть одинаковым, иначе форма выдаёт наш список подписчиков.
    say(msg, 'Если такой адрес у нас есть, письмо со ссылкой уже отправлено. Проверьте почту, в том числе папку со спамом.');
    btn.textContent = 'Отправлено';
  } catch (e) {
    say(msg, e.offline ? NET_DOWN : e.message, true);
    btn.disabled = false;
    btn.textContent = 'Прислать ссылку';
  }
});

/* --------------------------------------------------- новый пароль по ссылке */

$('#resetForm')?.addEventListener('submit', async ev => {
  ev.preventDefault();
  const token = new URL(location.href).searchParams.get('reset');
  const btn = $('#resetSubmit'), msg = $('#resetMsg');
  btn.disabled = true;
  btn.textContent = 'Сохраняем…';
  try {
    await call('/password/reset', { token, password: $('#resetPassword').value });
    $('#resetPassword').value = '';
    // Токен из адресной строки убираем: он одноразовый, но оставлять его в
    // истории браузера и в заголовке referer незачем.
    history.replaceState(null, '', location.pathname);
    await boot();
  } catch (e) {
    say(msg, e.offline ? NET_DOWN : e.message, true);
    btn.disabled = false;
    btn.textContent = 'Сохранить пароль';
  }
});

/* ------------------------------------------------------------------ кабинет */

function paintCabinet(me) {
  $('#accEmail').textContent = me.email || '—';
  $('#accPlan').textContent = PLAN_NAME[me.plan] || me.plan || '—';
  $('#accUntil').textContent = me.until ? fmtDate(me.until) : 'нет активной подписки';
  $('#accVerified').textContent = me.verified ? 'да' : 'нет';
  $('#notifyBox').checked = !!me.notify;
  $('#accFine').textContent = me.until
    ? 'Продление и отмена — на стороне платёжной системы.'
    : 'Открытая часть барометра доступна без подписки и остаётся бесплатной.';

  if (!me.verified) {
    say($('#notifyMsg'), 'Адрес пока не подтверждён. Уведомления придут только на подтверждённый адрес — ссылка была в письме после регистрации.');
  } else {
    $('#notifyMsg').hidden = true;
  }
  show('cabinet');
}

$('#notifyBox')?.addEventListener('change', async ev => {
  const on = ev.target.checked;
  try {
    await call('/notify', { on });
    say($('#notifyMsg'), on ? 'Уведомления включены.' : 'Уведомления отключены.');
  } catch (e) {
    ev.target.checked = !on;      // не сохранилось — галочка не должна врать
    say($('#notifyMsg'), e.offline ? NET_DOWN : e.message, true);
  }
});

$('#changeBtn')?.addEventListener('click', () => {
  const f = $('#changeForm');
  f.hidden = !f.hidden;
  if (!f.hidden) $('#oldPassword').focus();
});

$('#changeForm')?.addEventListener('submit', async ev => {
  ev.preventDefault();
  const btn = $('#changeSubmit'), msg = $('#changeMsg');
  btn.disabled = true;
  btn.textContent = 'Сохраняем…';
  try {
    await call('/password/change', {
      old_password: $('#oldPassword').value,
      password: $('#newPassword').value,
    });
    $('#oldPassword').value = $('#newPassword').value = '';
    $('#changeForm').hidden = true;
    say(msg, 'Пароль изменён. Входы на других устройствах закрыты.');
  } catch (e) {
    say(msg, e.offline ? NET_DOWN : e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Сохранить';
  }
});

$('#logoutBtn')?.addEventListener('click', async () => {
  try {
    await call('/logout', {});
  } catch (e) { /* выходим в любом случае: кука всё равно станет негодной */ }
  setMode('signin');
  show('auth');
});

/* --------------------------------------------------------------------- старт */

/**
 * Форма входа плюс весть о том, чем кончился переход по ссылке из письма.
 *
 * Вынесено отдельно, потому что на эту форму мы попадаем двумя путями:
 * сервер ответил «не вошёл» и сервер не ответил вовсе. Сообщение о
 * подтверждении нужно в обоих — иначе человек, кликнувший ссылку в момент
 * сбоя API, не узнает, сработала она или нет.
 */
function toAuth(params) {
  setMode('signin');
  show('auth');
  const v = params.get('verified');
  if (v === '1') say($('#authMsg'), 'Адрес подтверждён. Теперь можно войти.');
  if (v === '0') say($('#authMsg'), 'Ссылка не сработала: она действует сутки и срабатывает один раз. Введите адрес и пароль — предложим выслать письмо заново.', true);
}

async function boot() {
  const params = new URL(location.href).searchParams;

  // Ссылка на смену пароля из письма. Показываем экран, не спрашивая сервер:
  // сессии у человека нет, а токен проверится при отправке пароля.
  if (params.get('reset')) { show('reset'); $('#resetPassword').focus(); return; }

  try {
    const me = await call('/me');
    if (me && me.email) {
      paintCabinet(me);
      if (params.get('verified') === '1') say($('#notifyMsg'), 'Адрес подтверждён.');
    } else {
      toAuth(params);
    }
  } catch (e) {
    // Отличаем «не вошёл» от «служба недоступна»: первое нормально,
    // второе — повод сказать правду, а не показывать форму молча.
    console.error('кабинет:', e);
    if (e.offline) show('offline');
    else toAuth(params);
  }
}

show('loading');
boot();
