'use strict';

const crypto = require('crypto');

const APP_VERSION = '10.4.26';
const APP_REV = '866';
const SIGN_KEY = 'apr1$AwP!wRRT$gJ/q.X24poeBInlUJC';
const COOKIE = (process.env.SMZDM_COOKIE || '').trim();
const SK = (process.env.SMZDM_SK || '').trim();
const USER_AGENT = process.env.SMZDM_USER_AGENT_APP ||
  `smzdm_android_V${APP_VERSION} rv:${APP_REV} (Android10.0;zh)smzdmapp`;

function result(data, exitCode = 0) {
  process.stdout.write(`BENEFIT_RESULT=${JSON.stringify(data)}\n`);
  process.exitCode = exitCode;
}

function cookieValue(name) {
  const match = COOKIE.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
  return match ? match[1] : '';
}

function signedForm(data = {}) {
  const body = {
    weixin: 1,
    basic_v: 0,
    f: 'android',
    v: APP_VERSION,
    time: `${Math.round(Date.now() / 1000)}000`,
    ...data,
  };
  const keys = Object.keys(body).filter((key) => body[key] !== '').sort();
  const raw = keys.map((key) => `${key}=${String(body[key]).replace(/\s+/, '')}`).join('&');
  body.sign = crypto.createHash('md5').update(`${raw}&key=${SIGN_KEY}`).digest('hex').toUpperCase();
  return new URLSearchParams(body).toString();
}

function requestKey() {
  return Array.from(crypto.randomBytes(18), (byte) => String(byte % 10)).join('');
}

async function request(path, data = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(`https://user-api.smzdm.com${path}`, {
      method: 'POST',
      headers: {
        Accept: '*/*',
        'Accept-Language': 'zh-Hans-CN;q=1',
        'Content-Type': 'application/x-www-form-urlencoded',
        'request_key': requestKey(),
        'User-Agent': USER_AGENT,
        Cookie: COOKIE,
      },
      body: signedForm(data),
      signal: controller.signal,
    });
    const text = await response.text();
    let payload;
    try { payload = JSON.parse(text); } catch { payload = {}; }
    return { httpStatus: response.status, payload };
  } finally {
    clearTimeout(timer);
  }
}

function classifyError(response) {
  if ([401, 403].includes(response.httpStatus)) return 'authentication_invalid';
  if (response.httpStatus === 429) return 'rate_limited';
  if (!response.httpStatus || response.httpStatus >= 500) return 'network_error';
  return 'business_failure';
}

async function main() {
  if (!COOKIE) return result({ execution: 'failed', sign_status: 'authentication_invalid', error_class: 'missing_SMZDM_COOKIE' }, 2);
  if (!cookieValue('sess')) return result({ execution: 'failed', sign_status: 'authentication_invalid', error_class: 'missing_sess_cookie' }, 2);
  if (!SK && !cookieValue('device_id')) {
    return result({ execution: 'failed', sign_status: 'authentication_invalid', error_class: 'missing_SMZDM_SK_or_device_id' }, 2);
  }

  const sign = await request('/checkin', {
    touchstone_event: '',
    sk: SK || '1',
    token: cookieValue('sess'),
    captcha: '',
  });
  if (sign.payload?.error_code != '0') {
    const message = String(sign.payload?.error_msg || sign.payload?.error_message || '');
    if (/已签到|already/i.test(message)) {
      return result({ execution: 'ok', sign_status: 'already_complete', reward_status: 'pending_confirmation' });
    }
    if (/验证码|验证|captcha/i.test(message)) {
      return result({ execution: 'failed', sign_status: 'human_required', error_class: 'captcha_required' }, 1);
    }
    if (/限制|风控|异常活动|restricted/i.test(message)) {
      return result({ execution: 'failed', sign_status: 'restriction_detected', error_class: 'restriction_detected' }, 1);
    }
    return result({ execution: 'failed', sign_status: 'status_unknown', error_class: classifyError(sign) }, 1);
  }

  const rewardQuery = await request('/checkin/all_reward');
  const view = await request('/checkin/show_view_v2');
  let extraStatus = 'no_reward';
  const rows = view.payload?.data?.rows || [];
  const continuous = rows.find((item) => item?.cell_type == '18001');
  const shouldClaim = Boolean(continuous?.cell_data?.checkin_continue?.continue_checkin_reward_show);
  if (shouldClaim) {
    const extra = await request('/checkin/extra_reward');
    extraStatus = extra.payload?.error_code == '0' ? 'confirmed' : 'pending_confirmation';
  }
  const signData = sign.payload?.data || {};
  return result({
    execution: 'ok',
    sign_status: 'new_complete',
    sign_days: signData.daily_num ?? null,
    reward_status: rewardQuery.payload?.error_code == '0' ? 'confirmed' : 'pending_confirmation',
    reward_amount: null,
    reward_unit: null,
    extra_reward_status: extraStatus,
  });
}

main().catch((error) => result({
  execution: 'failed',
  sign_status: 'network_error',
  error_class: error?.name === 'AbortError' ? 'request_timeout' : 'network_error',
}, 1));
