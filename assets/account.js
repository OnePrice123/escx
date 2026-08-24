/* ═══════════════════════════════════════════════════════════
   Личный кабинет. Вход по адресу почты и паролю.

   Кабинет и барометр разделены намеренно: витрина статическая и работает,
   даже когда Worker лежит. Поэтому здесь ни одна ошибка сети не должна
   выглядеть как ошибка пользователя — если служба входа молчит, так и
   написано, а не «неверный адрес».

   Второе правило, из-за которого код выглядит так: причина отказа при входе
   берётся с сервера и НЕ уточняется на клиенте. Сервер отвечает одинаково на
   неверный пароль и на незнакомый адрес; если здесь дописать «проверьте,
   зарегистрированы ли вы», вся эта осторожность пропадёт зря.

   Приходит она КЛЮЧОМ. Раньше сервер присылал готовую русскую фразу, и
   кабинет показывал её кириллицей на любом языке. Теперь фраза тоже
   приходит — в поле error, — но она запасная: на экран идёт перевод по
   ключу, а сама фраза только если ключа в словаре нет.
   ═══════════════════════════════════════════════════════════ */

const API = '/api';
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

/* Сообщение помнит, ИЗ ЧЕГО оно получилось: ключ словаря и подстановки.
 * Без этого смена языка оставляла на экране фразу на прежнем языке — не
 * ошибка расчёта, но ровно тот стык, на котором перевод и выглядит
 * недоделанным. Ключ 'err:*' означает словарь отказов сервера. */
function say(node, key, bad = false, vars = null) {
  node.hidden = false;
  node.dataset.msgKey = key || '';
  node.dataset.msgVars = vars ? JSON.stringify(vars) : '';
  node.textContent = msgText(key, vars);
  node.classList.toggle('acc__msg--bad', bad);
}

/* Готовая фраза без ключа: единственный случай — сервер вернул причину,
 * которой нет в словаре. Переезжать ей не с чем, и это честнее пустоты. */
function sayRaw(node, text, bad = false) {
  node.hidden = false;
  node.dataset.msgKey = '';
  node.dataset.msgVars = '';
  node.textContent = text;
  node.classList.toggle('acc__msg--bad', bad);
}

function msgText(key, vars) {
  if (!key) return '';
  if (key.startsWith('err:')) {
    const m = (I18N[LANG] && I18N[LANG].accErrors) || (I18N.en && I18N.en.accErrors) || {};
    const s = m[key.slice(4)] || '';
    return s.replace('{n}', (vars && vars.n) ?? '');
  }
  return t(key);
}

/* Перерисовать сообщения, уже стоящие на экране. Зовётся при смене языка. */
function repaintMessages() {
  document.querySelectorAll('.acc__msg').forEach(n => {
    const key = n.dataset.msgKey;
    if (key) n.textContent = msgText(key, n.dataset.msgVars ? JSON.parse(n.dataset.msgVars) : null);
  });
}

/* Показать отказ: сперва перевод по ключу, потом — фраза сервера.
 * Порядок именно такой. Если однажды сервер вернёт ключ, которого здесь нет,
 * человек увидит русскую фразу вместо пустого места — это плохо, но честно,
 * а пустое сообщение об ошибке означало бы, что всё в порядке. */
function sayErr(node, e) {
  if (e.offline) return say(node, 'accNetDown', true);
  const key = e.data?.key;
  const m = (I18N[LANG] && I18N[LANG].accErrors) || (I18N.en && I18N.en.accErrors) || {};
  if (key && m[key]) return say(node, 'err:' + key, true, { n: e.data?.n });
  return sayRaw(node, e.message || t('accNetDown'), true);
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
    throw Object.assign(new Error('offline'), { offline: true });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || `HTTP ${res.status}`), { data });
  return data;
}

/* ------------------------------------------------------- вход и регистрация */

let mode = 'signin';   // signin | register

function setMode(next) {
  mode = next;
  const reg = mode === 'register';
  $('#authTitle').textContent = t(reg ? 'accRegister' : 'accSignIn');
  $('#authLede').textContent = t(reg ? 'accLedeRegister' : 'accLedeSignIn');
  $('#authBtn').textContent = t(reg ? 'accRegisterBtn' : 'accSignInBtn');
  $('#modeBtn').textContent = t(reg ? 'accToSignIn' : 'accToRegister');
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
    say(msg, 'accPwShortLocal', true);
    return;
  }

  btn.disabled = true;
  btn.textContent = t(mode === 'register' ? 'accCreating' : 'accSigningIn');
  msg.hidden = true;
  try {
    const r = await call(mode === 'register' ? '/register' : '/signin',
                         { email, password, lang: LANG });
    $('#password').value = '';
    // Регистрация прошла, но сессии нет: адрес ждёт подтверждения.
    if (r.pending) { toPending(email, password); return; }
    await boot();
  } catch (e) {
    // Пароль верный, но адрес не подтверждён — это не ошибка ввода, и
    // держать человека на форме входа, где он будет пробовать пароль
    // заново, незачем.
    if (e.data?.code === 'unverified') { toPending(email, password); return; }

    sayErr(msg, e);
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
  btn.textContent = t(mode === 'register' ? 'accRegisterBtn' : 'accSignInBtn');
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
    say($('#authMsg'), 'accResendAgain');
    return;
  }

  btn.disabled = true;
  btn.textContent = t('accSending');
  try {
    const r = await call('/verify/resend', { ...lastCreds, lang: LANG });
    say(msg, r.verified ? 'accAlreadyVerified' : 'accResent');
    btn.textContent = t('accSent');   // намеренно не включаем обратно
  } catch (e) {
    sayErr(msg, e);
    btn.disabled = false;
    btn.textContent = t('accResend');
  }
});

/* ------------------------------------------------------------ забытый пароль */

$('#forgotForm')?.addEventListener('submit', async ev => {
  ev.preventDefault();
  const btn = $('#forgotSubmit'), msg = $('#forgotMsg');
  btn.disabled = true;
  btn.textContent = t('accSending');
  try {
    await call('/password/forgot', { email: $('#forgotEmail').value.trim(), lang: LANG });
    // Ответ сервера одинаков для любого адреса — значит и текст здесь
    // обязан быть одинаковым, иначе форма выдаёт наш список подписчиков.
    say(msg, 'accForgotSent');
    btn.textContent = t('accSent');
  } catch (e) {
    sayErr(msg, e);
    btn.disabled = false;
    btn.textContent = t('accForgotSubmit');
  }
});

/* --------------------------------------------------- новый пароль по ссылке */

$('#resetForm')?.addEventListener('submit', async ev => {
  ev.preventDefault();
  const token = new URL(location.href).searchParams.get('reset');
  const btn = $('#resetSubmit'), msg = $('#resetMsg');
  btn.disabled = true;
  btn.textContent = t('accSaving');
  try {
    await call('/password/reset', { token, password: $('#resetPassword').value });
    $('#resetPassword').value = '';
    // Токен из адресной строки убираем: он одноразовый, но оставлять его в
    // истории браузера и в заголовке referer незачем.
    history.replaceState(null, '', location.pathname);
    await boot();
  } catch (e) {
    sayErr(msg, e);
    btn.disabled = false;
    btn.textContent = t('accResetSubmit');
  }
});

/* ------------------------------------------------------------------ кабинет */

function paintCabinet(me) {
  $('#accEmail').textContent = me.email || '—';
  $('#accPlan').textContent = t2('plans', me.plan, me.plan) || '—';
  $('#accUntil').textContent = me.until ? fmtDay(me.until) : t('accNoSub');
  $('#accVerified').textContent = t(me.verified ? 'accYes' : 'accNo');
  $('#notifyBox').checked = !!me.notify;
  $('#accFine').textContent = t(me.until ? 'accFinePaid' : 'accFineFree');

  if (!me.verified) {
    say($('#notifyMsg'), 'accNotifyUnverified');
  } else {
    $('#notifyMsg').hidden = true;
  }
  show('cabinet');
}

$('#notifyBox')?.addEventListener('change', async ev => {
  const on = ev.target.checked;
  try {
    await call('/notify', { on });
    say($('#notifyMsg'), on ? 'accNotifyOn' : 'accNotifyOff');
  } catch (e) {
    ev.target.checked = !on;      // не сохранилось — галочка не должна врать
    sayErr($('#notifyMsg'), e);
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
  btn.textContent = t('accSaving');
  try {
    await call('/password/change', {
      old_password: $('#oldPassword').value,
      password: $('#newPassword').value,
    });
    $('#oldPassword').value = $('#newPassword').value = '';
    $('#changeForm').hidden = true;
    say(msg, 'accChanged');
  } catch (e) {
    sayErr(msg, e);
  } finally {
    btn.disabled = false;
    btn.textContent = t('accSave');
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
  if (v === '1') say($('#authMsg'), 'accVerifiedOk');
  if (v === '0') say($('#authMsg'), 'accVerifiedFail', true);
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
      if (params.get('verified') === '1') say($('#notifyMsg'), 'accVerifiedShort');
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

/* Смена языка перерисовывает всё, что видно: разметку, подписи форм и уже
   стоящие на экране сообщения — каждое помнит свой ключ. */
buildLangPicker(() => { applyLang(); setMode(mode); repaintMessages(); });
applyLang();
setMode('signin');

show('loading');
boot();
