"""Bounded V2EX provider entry; success requires today's reward record."""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from dailycheckin.v2ex.main import V2ex


class BoundedSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs['timeout'] = 30
        return super().request(method, url, **kwargs)


def main():
    raw = os.getenv('V2EX')
    accounts = json.loads(raw) if raw else [{'cookie': os.getenv('V2EX_COOKIE', '')}]
    if not isinstance(accounts, list) or not accounts:
        raise ValueError('missing_accounts')
    today = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    outcomes = []
    for item in accounts:
        try:
            cookie = item.get('cookie', '').strip()
            if not cookie or '\n' in cookie or '\r' in cookie:
                raise ValueError('missing_or_invalid_cookie')
            with BoundedSession() as session:
                session.headers.update({'Cookie': cookie, 'User-Agent': os.getenv('V2EX_USER_AGENT', 'Mozilla/5.0'), 'Accept-Language': 'zh-CN,zh;q=0.9'})
                proxy = item.get('proxy') or os.getenv('V2EX_PROXY')
                if proxy:
                    session.proxies.update({'http': proxy, 'https': proxy})
                fields = {row.get('name'): str(row.get('value', '')) for row in V2ex.sign(session)}
            reward = fields.get('今日签到', '')
            success = today in reward and '每日登录奖励' in reward and '签到失败' not in fields
            outcomes.append({'success': success, 'reason': None if success else 'reward_not_confirmed',
                             'streak_warning': '失败' in fields.get('签到天数', '')})
        except Exception as error:
            outcomes.append({'success': False, 'reason': type(error).__name__})
    success = all(item['success'] for item in outcomes)
    print('BENEFIT_RESULT=' + json.dumps({'platform': 'v2ex', 'success': success,
          'reason': None if success else 'account_failed', 'accounts': outcomes}, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, TypeError) as error:
        print('BENEFIT_RESULT=' + json.dumps({'platform': 'v2ex', 'success': False, 'reason': type(error).__name__}))
        raise SystemExit(2)
