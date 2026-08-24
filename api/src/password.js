/* Пароли.
 *
 * Раньше паролей здесь не было вовсе — вход шёл по ссылке из письма. Решение
 * отменено сознательно: ссылка требует работающей отправки почты, а кабинет
 * из-за этого стоял. Пароль даёт вход, который не зависит ни от одного
 * внешнего сервиса. Ссылка осталась, но теперь она восстанавливает пароль.
 *
 * Алгоритм — PBKDF2-HMAC-SHA256 из WebCrypto. Не потому что он лучший
 * (argon2id лучше), а потому что в Worker нет нативных модулей, а зависимости
 * в этом проекте не заводятся: WebCrypto предлагает из медленных функций
 * только PBKDF2.
 *
 * ГЛАВНОЕ, ЧТО НУЖНО ПОНИМАТЬ ПРО ЧИСЛО ИТЕРАЦИЙ.
 * OWASP просит для PBKDF2-SHA256 порядка 600 000 итераций. Столько поставить
 * нельзя по двум независимым причинам:
 *   1. workerd отвергает запрос выше ста тысяч:
 *      «Pbkdf2 failed: iteration counts above 100000 are not supported».
 *   2. На бесплатном тарифе Worker получает 10 мс процессорного времени на
 *      запрос. Сто тысяч итераций в это не укладываются — запрос упадёт.
 * То есть мы работаем на порядок ниже рекомендации, и признать это честнее,
 * чем написать в комментарии «безопасно».
 *
 * Дырка закрывается ПЕРЦЕМ: перед PBKDF2 пароль прогоняется через HMAC с
 * секретом, который лежит в секретах Worker и в базу не попадает никогда.
 * Утечка дампа D1 после этого не даёт перебирать пароли офлайн вообще — без
 * перца перебор бессмысленен независимо от числа итераций. Соль защищает от
 * радужных таблиц, итерации — от быстрого перебора, перец — от перебора по
 * украденной базе. Это три разные задачи, и перец здесь несёт основную.
 */
import { sha256Hex, timingSafeEqual, randomToken } from './util.js';

/* ЧИСЛО ИЗМЕРЕНО, А НЕ ВЫБРАНО НА ГЛАЗ.
 *
 * Замер на машине разработки (Node, тот же BoringSSL-класс скорости):
 *     32 000 итераций → 17.1 мс
 *     50 000 итераций → 24.5 мс
 *    100 000 итераций → 48.6 мс
 * Бюджет бесплатного тарифа — 10 мс CPU на запрос, и вход тратит ровно один
 * такой расчёт. Первая версия стояла на 32 000: тесты зелёные, а в проде вход
 * упал бы по лимиту CPU. Отсюда 16 000 — примерно 8–9 мс, с запасом на то,
 * что в workerd скорость другая.
 *
 * Перейдёте на платный тариф Workers (30 с CPU) — ставьте 100 000 прямо здесь
 * одной правкой: старые хэши несут свои параметры внутри себя и пережмутся
 * сами при первом успешном входе, см. needsRehash. Никакой миграции не нужно.
 *
 * Померить заново:
 *   node -e "import('./src/password.js').then(async m => {
 *     const t=Date.now(); for(let i=0;i<10;i++) await m.hashPassword('x','p');
 *     console.log((Date.now()-t)/10,'мс') })"
 */
export const HASH_ITERS = 16_000;
export const HASH_ITERS_MAX = 100_000;   // предел платформы, не наш выбор

export const MIN_PASSWORD = 10;
export const MAX_PASSWORD = 200;         // выше — только трата CPU на PBKDF2

/* Двадцать паролей, которыми ломают всё. Полного списка здесь быть не может
 * и не нужно: он весит мегабайты, а эти двадцать закрывают заметную долю. */
const COMMON = new Set([
  'password', 'password1', 'password123', '1234567890', '123456789', '12345678',
  'qwertyuiop', 'qwerty123', 'iloveyou', 'admin123', 'welcome1', 'letmein1',
  'passw0rd', 'football1', 'superman1', 'sunshine1', 'princess1', 'monkey123',
  'dragon123', 'baseball1',
]);

/**
 * Нормализация. Обязательна и заморожена: если завтра поменять форму
 * нормализации, все существующие хэши перестанут совпадать с теми же
 * паролями, набранными на другой раскладке или с другой клавиатуры.
 */
function normalize(p) {
  return String(p == null ? '' : p).normalize('NFKC');
}

/**
 * Проверка пароля на пригодность. Возвращает причину отказа или null.
 * Требований намеренно немного: набор обязательных символов не повышает
 * стойкость, а гонит человека к «Passw0rd!». Длина повышает.
 */
export function checkPasswordPolicy(password) {
  const p = normalize(password);
  // Возвращается ПАРА: ключ для интерфейса и русская фраза запасом. Раньше
  // отсюда уходила только фраза, и кабинет на любом языке показывал её
  // кириллицей. Ключ — единственное, что можно перевести на стороне читателя.
  if (p.length < MIN_PASSWORD)
    return { key: 'pwShort', reason: `пароль короче ${MIN_PASSWORD} символов`, n: MIN_PASSWORD };
  if (p.length > MAX_PASSWORD)
    return { key: 'pwLong', reason: `пароль длиннее ${MAX_PASSWORD} символов`, n: MAX_PASSWORD };
  if (COMMON.has(p.toLowerCase()))
    return { key: 'pwCommon', reason: 'слишком распространённый пароль' };
  if (new Set(p).size < 4)
    return { key: 'pwPoor', reason: 'слишком мало разных символов' };
  return null;
}

/** Перец: HMAC поверх пароля. Пустой перец означает «секрет не задан». */
async function pepperize(password, pepper) {
  const p = normalize(password);
  if (!pepper) return { material: new TextEncoder().encode(p), peppered: 0 };
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(String(pepper)),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(p));
  return { material: new Uint8Array(mac), peppered: 1 };
}

async function derive(material, saltHex, iters) {
  const salt = Uint8Array.from(saltHex.match(/../g).map(h => parseInt(h, 16)));
  const key = await crypto.subtle.importKey('raw', material, 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: iters }, key, 256);
  return [...new Uint8Array(bits)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Хэш для записи в базу.
 *
 * Формат: pbkdf2$sha256$<итерации>$p<0|1>$<соль>$<хэш>
 * Параметры лежат внутри строки, а не в коде, иначе смена числа итераций
 * разом обнулит все существующие пароли. Инвариант проекта «версионируется
 * всё» относится и к этому.
 */
export async function hashPassword(password, pepper = '', iters = HASH_ITERS) {
  if (iters > HASH_ITERS_MAX) throw new Error(`итераций больше ${HASH_ITERS_MAX} платформа не примет`);
  const salt = randomToken(16);
  const { material, peppered } = await pepperize(password, pepper);
  const dk = await derive(material, salt, iters);
  return `pbkdf2$sha256$${iters}$p${peppered}$${salt}$${dk}`;
}

/**
 * Проверка пароля. Возвращает { ok, needsRehash }.
 *
 * needsRehash поднимается, когда запись сделана по устаревшим параметрам:
 * меньше итераций, чем сейчас, или без перца, когда перец уже появился.
 * Вызывающий обязан в этом случае перезаписать хэш — иначе секрет, который
 * вы завели, так и не начнёт защищать старые записи.
 */
export async function verifyPassword(stored, password, pepper = '') {
  const parts = String(stored || '').split('$');
  if (parts.length !== 6 || parts[0] !== 'pbkdf2' || parts[1] !== 'sha256')
    return { ok: false, needsRehash: false };

  const iters = Number(parts[2]);
  const wasPeppered = parts[3] === 'p1';
  const [, , , , salt, dk] = parts;
  if (!Number.isInteger(iters) || iters < 1 || iters > HASH_ITERS_MAX || !/^[0-9a-f]+$/.test(salt))
    return { ok: false, needsRehash: false };

  // Перец берётся тот, что записан в хэше, а не тот, что задан сейчас:
  // иначе после появления секрета никто не сможет войти вообще.
  const { material } = await pepperize(password, wasPeppered ? pepper : '');
  const ok = timingSafeEqual(await derive(material, salt, iters), dk);

  const stale = iters < HASH_ITERS || (!wasPeppered && !!pepper);
  return { ok, needsRehash: ok && stale };
}

/**
 * Заглушка постоянной стоимости для несуществующего адреса.
 *
 * Без неё «нет такого пользователя» отвечает мгновенно, а «неверный пароль» —
 * через PBKDF2, и форма входа по времени ответа выдаёт, кто у нас
 * зарегистрирован. Здесь считается ровно та же функция и результат
 * выбрасывается.
 */
export async function burnTime(pepper = '') {
  const { material } = await pepperize('нет такого пользователя', pepper);
  await derive(material, await sha256Hex('dummy'), HASH_ITERS);
}
