"""Narrow Selenium binding to the pinned Rainyun page and Tencent challenge."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from common.details import number
from platforms.rainyun.provider import read_provider

ORIGIN = "https://app.rainyun.com"
EARN_URL = ORIGIN + "/account/reward/earn"
# Exact daily row, rather than another task's identical reward button.
CHECKIN_ROW = ('//*[@id="app"]/div[1]/div[3]/div[2]/div/div/div[2]/div[2]'
               '/div/div/div/div[1]/div//div/div[1]'
               '/div[span[1][normalize-space(text())="每日签到"]]/span[2]')
LOGIN_BUTTON = '//*[@id="app"]/div[1]/div[1]/div/div[2]/fade/div/div/span/form/button'
LOGIN_ERROR = '/html/body/div[4]/div[2]/div/div/div[1]/div/div/div/div/small'
CONFIRM_CAPTCHA = '//*[@id="tcStatus"]/div[2]/div[2]/div/div'
LOGIN_REJECTIONS = ("密码错误", "账号不存在", "用户名或密码", "登录失败", "账户或密码", "账号或密码")
DIRECTORY = Path(__file__).resolve().parent


class RainyunError(Exception):
    """Only a fixed reason, never page text or credential data, is reported."""


def checkin_state(text):
    return {"已完成": "complete", "领取奖励": "incomplete"}.get(text.strip(), "unknown")


def click_offsets(matches, image_size, element_size):
    """Convert ordered ICR image coordinates to Selenium's center-relative offsets."""
    width, height = image_size
    shown_width, shown_height = element_size
    if (not isinstance(matches, list) or len(matches) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                   for v in (width, height, shown_width, shown_height))):
        raise RainyunError("captcha_recognition_failed")
    try:
        if sorted(match["sprite_idx"] for match in matches) != [0, 1, 2]:
            raise ValueError
        offsets = []
        for match in sorted(matches, key=lambda row: row["sprite_idx"]):
            x, y, w, h = match["bg_rect"]
            if (any(type(v) not in (int, float) or not math.isfinite(v)
                    for v in (x, y, w, h)) or x < 0 or y < 0 or w <= 0 or h <= 0
                    or x + w > width or y + h > height):
                raise ValueError
            offsets.append((round(((x + w / 2) / width - 0.5) * shown_width),
                            round(((y + h / 2) / height - 0.5) * shown_height)))
        if len(set(offsets)) != 3:
            raise ValueError
        return offsets
    except (KeyError, TypeError, ValueError):
        raise RainyunError("captcha_recognition_failed") from None


def verify_runtime(config):
    expected = json.loads((DIRECTORY / "browser-contract.json").read_text())["version"]
    for field in ("chromium_path", "chromedriver_path"):
        path = Path(config[field])
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RainyunError("browser_runtime_unavailable")
        try:
            output = subprocess.check_output([str(path), "--version"], timeout=10,
                                             stderr=subprocess.DEVNULL, text=True)
        except (OSError, subprocess.SubprocessError):
            raise RainyunError("browser_runtime_unavailable") from None
        version = re.search(r"\b\d+\.\d+\.\d+\.\d+\b", output)
        if not version or version[0] != expected:
            raise RainyunError("browser_version_mismatch")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RainyunError("captcha_image_unavailable")


class Browser:
    def __init__(self, config, directory, *, cookies=None, clock=time.monotonic, sleep=time.sleep):
        self.config, self.directory = config, Path(directory)
        self.clock, self.sleep = clock, sleep
        self.driver = None
        self.temporary = None
        self.login_attempted = False
        self.captcha_attempts = 0
        self.cookies = cookies
        self.identity_confirmed = False

    def open(self):
        verify_runtime(self.config)
        try:
            self.recognize, stealth = read_provider(self.config["provider_root"])
        except ImportError:
            raise RainyunError("dependency_unavailable") from None
        except (OSError, ValueError) as error:
            reason = str(error) if str(error) in {"upstream_missing", "dependency_incompatible"} else "upstream_missing"
            raise RainyunError(reason) from None
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.common.exceptions import TimeoutException, WebDriverException
            from selenium.webdriver.common.action_chains import ActionChains
        except ImportError:
            raise RainyunError("dependency_unavailable") from None
        self.Wait, self.Timeout = WebDriverWait, TimeoutException
        self.WebDriverError, self.Actions = WebDriverException, ActionChains
        profile = self.directory / "browser"
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        options = Options()
        options.binary_location = self.config["chromium_path"]
        options.page_load_strategy = "eager"
        for argument in ("--headless=new", "--window-size=1920,1080", "--disable-dev-shm-usage",
                         "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}"):
            options.add_argument(argument)
        if self.config.get("proxy"):
            options.add_argument("--proxy-server=" + self.config["proxy"])
        # Passing an explicit executable prevents Selenium Manager downloads.
        # common.runner's private run path is too long for Chromium's Unix
        # SingletonSocket (108-byte limit). Keep only this process's temporary
        # files under a short private path; the persistent profile stays above.
        self.temporary = tempfile.TemporaryDirectory(prefix="rainyun-", dir="/tmp")
        environment = {**os.environ, "TMPDIR": self.temporary.name}
        service = Service(executable_path=self.config["chromedriver_path"],
                          log_output=subprocess.DEVNULL, env=environment)
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.set_page_load_timeout(30)
        self.driver.set_script_timeout(15)
        self.driver.implicitly_wait(0)
        self.driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"})
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth})
        if self.cookies is not None:
            self.driver.execute_cdp_cmd("Network.setCookies", {"cookies": self.cookies})
            # Rainyun's route guard reads the full Vue user cache. A cold
            # profile with only cookies can be redirected before its async
            # /user/ request fills localStorage. Let the official public page
            # initialize that cache before opening the protected reward route.
            self.driver.get(ORIGIN + "/")
            self._official()
            initialized = """
              const raw=localStorage.getItem('user-data');
              if(!raw) return false;
              try { const user=JSON.parse(raw);
                return Number.isInteger(user.ID) && user.ID>0 && !!user.meta;
              } catch (_) { return false; }
            """
            try:
                self.Wait(self.driver, 20, poll_frequency=0.25).until(
                    lambda _: self.driver.execute_script(initialized))
            except self.Timeout:
                raise RainyunError("cookiecloud_session_not_initialized") from None

    def _one(self, kind, selector, *, clickable=False):
        matches = self.driver.find_elements(kind, selector)
        if len(matches) > 16:
            raise RainyunError("page_structure_unknown")
        shown = [element for element in matches if element.is_displayed()]
        if len(shown) > 1:
            raise RainyunError("page_structure_unknown")
        return shown[0] if shown and (not clickable or shown[0].is_enabled()) else None

    def _wait_one(self, kind, selector, *, clickable=False, seconds=15):
        return self.Wait(self.driver, seconds, poll_frequency=0.25).until(
            lambda _: self._one(kind, selector, clickable=clickable))

    def _official(self):
        location = urlsplit(self.driver.current_url)
        if (location.scheme != "https" or location.hostname != "app.rainyun.com"
                or location.port not in (None, 443) or location.username or location.password):
            raise RainyunError("unexpected_origin")
        return location.path

    def _navigate(self):
        try:
            self.driver.get(EARN_URL)
        except self.Timeout:
            self._official()
            # A real rendered business/login marker can survive a slow subresource.
            if not (self._one("xpath", CHECKIN_ROW)
                    or self._one("css selector", "input[name='login-field']")):
                raise RainyunError("browser_timeout") from None
            self.driver.execute_script("window.stop();")
        return self._official()

    def _frame(self):
        return self._one("css selector", "iframe[id^='tcaptcha_iframe']")

    def _login_rejected(self):
        elements = self.driver.find_elements("xpath", LOGIN_ERROR)
        if len(elements) > 16:
            raise RainyunError("page_structure_unknown")
        return any(any(word in element.text for word in LOGIN_REJECTIONS) for element in elements)

    def _login(self):
        if self.login_attempted:
            raise RainyunError("authentication_invalid")
        self.login_attempted = True
        self._official()
        username = self._wait_one("css selector", "input[name='login-field']")
        password = self._wait_one("css selector", "input[name='login-password']")
        username.clear()
        username.send_keys(self.config["username"])
        password.clear()
        password.send_keys(self.config["password"])
        self._wait_one("xpath", LOGIN_BUTTON, clickable=True).click()
        deadline, captcha_handled = self.clock() + 60, False
        while self.clock() < deadline:
            path = self._official()
            if path.startswith(("/dashboard", "/account/")):
                self._navigate()
                return
            if self._login_rejected():
                raise RainyunError("authentication_invalid")
            frame = self._frame()
            if frame is not None and not captcha_handled:
                self._solve_captcha(frame)
                captcha_handled = True
            self.sleep(0.5)
        raise RainyunError("login_not_confirmed")

    def read(self):
        if self._navigate().startswith("/auth/login"):
            if self.config.get("cookiecloud_config"):
                raise RainyunError("authentication_invalid")
            self._login()
        if self._official() != "/account/reward/earn":
            raise RainyunError("login_not_confirmed")
        element = self._wait_one("xpath", CHECKIN_ROW)
        state = checkin_state(element.text)
        return {"checkin": state, "balance": self._balance()}

    def _balance(self):
        # This is the official client's user-summary endpoint. Transfer only the
        # fields needed for account binding and points, never the full response.
        script = """
          const done=arguments[arguments.length-1];
          const csrf=document.cookie.split(';').map(x=>x.trim())
            .find(x=>x.startsWith('X-CSRF-Token='));
          const control=new AbortController();
          const timer=setTimeout(()=>control.abort(),10000);
          fetch('https://api.v2.rainyun.com/user/?no_cache=true',{
            credentials:'include',signal:control.signal,
            headers:{'Accept':'application/json','X-CSRF-Token':csrf?decodeURIComponent(csrf.slice(13)):''}
          }).then(r=>r.json()).then(body=>done({
            code:body.code,points:body.data?.Points,user_id:body.data?.ID
          })).catch(()=>done({code:null})).finally(()=>clearTimeout(timer));
        """
        try:
            observed = self.driver.execute_async_script(script)
        except (self.Timeout, self.WebDriverError):
            observed = None
        if not isinstance(observed, dict):
            if self.config.get("cookiecloud_config") and not self.identity_confirmed:
                raise RainyunError("account_identity_unconfirmed")
            return None
        if observed.get("code") in {30002, 30038}:
            raise RainyunError("authentication_invalid")
        if observed.get("code") != 200:
            if self.config.get("cookiecloud_config") and not self.identity_confirmed:
                raise RainyunError("account_identity_unconfirmed")
            return None
        if self.config.get("cookiecloud_config"):
            identifier = observed.get("user_id")
            if type(identifier) is not int or identifier <= 0:
                raise RainyunError("account_identity_unconfirmed")
            expected = hashlib.sha256(f"rainyun-user-id:{identifier}".encode()).hexdigest()[:24]
            if expected != self.directory.name:
                raise RainyunError("account_identity_mismatch")
            self.identity_confirmed = True
        balance = number(observed.get("points"))
        return balance if balance is not None and balance >= 0 else None

    def _dismiss_success(self):
        # Only acknowledge a known result, not arbitrary terms/security dialogs.
        selector = ("//footer[contains(@id,'modal') and contains(@id,'footer')]"
                    "//button[normalize-space(.)='确认']")
        button = self._one("xpath", selector, clickable=True)
        if button is not None:
            text = button.find_element("xpath", "../..").text
            if any(word in text for word in ("签到成功", "领取成功", "登录成功")):
                button.click()

    def claim(self, before_submit):
        self._official()
        element = self._wait_one("xpath", CHECKIN_ROW, clickable=True)
        state = checkin_state(element.text)
        if state == "complete":
            return
        if state != "incomplete":
            raise RainyunError("checkin_state_unknown")
        links = element.find_elements("xpath", "./a")
        if len(links) > 1:
            raise RainyunError("page_structure_unknown")
        target = links[0] if links else element
        before_submit()
        target.click()
        deadline, captcha_handled = self.clock() + 60, False
        while self.clock() < deadline:
            self._official()
            element = self._one("xpath", CHECKIN_ROW)
            if element is not None and checkin_state(element.text) == "complete":
                return
            frame = self._frame()
            if frame is not None and not captcha_handled:
                self._solve_captcha(frame)
                captcha_handled = True
            self._dismiss_success()
            self.sleep(0.5)
        raise RainyunError("claim_readback_timeout")

    def _image(self, url):
        target = urlsplit(url)
        if (target.scheme != "https" or target.port not in (None, 443)
                or target.hostname not in {"t.captcha.qq.com", "turing.captcha.qcloud.com", "captcha.gtimg.com"}
                or target.username or target.password):
            raise RainyunError("captcha_image_origin_unknown")
        proxy = self.config.get("proxy")
        opener = build_opener(NoRedirect(), ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))
        ua = self.driver.execute_script("return navigator.userAgent")
        try:
            with opener.open(Request(url, headers={"User-Agent": ua}), timeout=15) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if response.status != 200 or len(raw) > 2 * 1024 * 1024:
                    raise RainyunError("captcha_image_unavailable")
                return raw
        except (OSError, ValueError):
            raise RainyunError("captcha_image_unavailable") from None

    def _solve_captcha(self, frame):
        import cv2
        import numpy as np
        self.driver.switch_to.frame(frame)
        try:
            while self.captcha_attempts < 2:
                self.captcha_attempts += 1
                background = self._wait_one("css selector", "#slideBg")
                style = background.get_attribute("style")
                image_url = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", style or "")
                if image_url is None:
                    raise RainyunError("captcha_image_unavailable")
                sprite = self._wait_one("css selector", "#instruction div img")
                bg_bytes = self._image(image_url[1])
                sprite_bytes = self._image(sprite.get_attribute("src"))
                image = cv2.imdecode(np.frombuffer(bg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None or not 0 < image.shape[0] <= 4096 or not 0 < image.shape[1] <= 4096:
                    raise RainyunError("captcha_image_unavailable")
                try:
                    matches = self.recognize(bg_bytes, sprite_bytes)
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", background)
                    offsets = click_offsets(matches, (image.shape[1], image.shape[0]),
                                            (background.rect["width"], background.rect["height"]))
                except RainyunError:
                    if self.captcha_attempts >= 2:
                        raise
                    self._wait_one("css selector", "#reload", clickable=True).click()
                    self.sleep(1)
                    continue
                for x, y in offsets:
                    self.Actions(self.driver).move_to_element_with_offset(background, x, y).click().perform()
                    self.sleep(0.3)
                self._wait_one("xpath", CONFIRM_CAPTCHA, clickable=True).click()

                def outcome(_):
                    element = self._one("css selector", "#tcOperation")
                    classes = (element.get_attribute("class") or "").split() if element else []
                    if "show-success" in classes:
                        return "success"
                    if "show-error" in classes:
                        return "rejected"
                    return False

                try:
                    observed = self.Wait(self.driver, 10, poll_frequency=0.25).until(outcome)
                except self.Timeout:
                    raise RainyunError("captcha_unconfirmed") from None
                except self.WebDriverError:
                    # The iframe can disappear on success. Only the parent page's
                    # subsequent business readback can establish what happened.
                    return
                if observed == "success":
                    return
                if self.captcha_attempts < 2:
                    self._wait_one("css selector", "#reload", clickable=True).click()
                    self.sleep(1)
            raise RainyunError("captcha_rejected")
        finally:
            self.driver.switch_to.default_content()

    def close(self):
        try:
            if self.driver is not None:
                self.driver.quit()
        finally:
            if self.temporary is not None:
                self.temporary.cleanup()
