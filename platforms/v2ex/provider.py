"""Minimal MIT V2EX provider extracted from dailycheckin 25.12.9.

See LICENSE.provider and provider-source.json. No package-wide imports.
"""

import re


class V2ex:
    @staticmethod
    def sign(session):
        msg = []
        response = session.get(url="https://www.v2ex.com/mission/daily", verify=True)
        pattern = (
            r"<input type=\"button\" class=\"super normal button\""
            r" value=\".*?\" onclick=\"location\.href = \'(.*?)\';\" />"
        )
        urls = re.findall(pattern=pattern, string=response.text)
        url = urls[0] if urls else None
        if url is None:
            return [{"name": "签到失败", "value": "cookie 可能过期"}]
        elif url != "/balance":
            headers = {"Referer": "https://www.v2ex.com/mission/daily"}
            data = {"once": url.split("=")[-1]}
            _ = session.get(
                url="https://www.v2ex.com" + url,
                verify=True,
                headers=headers,
                params=data,
            )
        response = session.get(url="https://www.v2ex.com/balance", verify=True)
        total = re.findall(
            pattern=r"<td class=\"d\" style=\"text-align: right;\">(\d+\.\d+)</td>",
            string=response.text,
        )
        total = total[0] if total else "签到失败"
        today = re.findall(
            pattern=r'<td class="d"><span class="gray">(.*?)</span></td>',
            string=response.text,
        )
        today = today[0] if today else "签到失败"
        username = re.findall(
            pattern=r"<a href=\"/member/.*?\" class=\"top\">(.*?)</a>",
            string=response.text,
        )
        username = username[0] if username else "用户名获取失败"
        msg += [
            {"name": "帐号信息", "value": username},
            {"name": "今日签到", "value": today},
            {"name": "帐号余额", "value": total},
        ]
        response = session.get(url="https://www.v2ex.com/mission/daily", verify=True)
        data = re.findall(
            pattern=r"<div class=\"cell\">(.*?)天</div>", string=response.text
        )
        data = data[0] + "天" if data else "获取连续签到天数失败"
        msg += [
            {"name": "签到天数", "value": data},
        ]
        return msg
