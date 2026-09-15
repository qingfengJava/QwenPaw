"""登录页品牌名文案的真实渲染验证。

login.title 改为 {{brand}} 插值后，必须确认在真实页面里占位符被正确替换
（而不是把 "{{brand}}" 字面量渲染出来），且不再出现上游项目名。

逐语言设置 localStorage.language，拦 /auth/status 强制停在登录页，读取标题文本。
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
OUT = Path(__file__).resolve().parent
LANGS = ["zh", "en", "ja", "ru", "id", "pt-BR", "vi"]

STATUS_BODY = '{"enabled": true, "has_users": true, "registration_enabled": false}'


def run() -> list[str]:
    """逐语言取登录页标题，返回校验事实行。"""
    lines: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for lang in LANGS:
            context = browser.new_context(
                viewport={"width": 1280, "height": 860},
                device_scale_factor=2,
            )
            context.add_init_script(
                "localStorage.setItem('qwenpaw-theme','light');"
                f"localStorage.setItem('language', '{lang}');"
            )
            page = context.new_page()
            page.route("**/*auth/status*", lambda route: route.fulfill(
                status=200, content_type="application/json", body=STATUS_BODY))
            page.goto(f"{BASE}/login", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            heading = page.locator("h2").first.inner_text().strip()
            wordmark = page.locator("div", has_text="SmartWork").first.inner_text().strip() \
                if page.get_by_text("SmartWork", exact=True).count() > 0 else "<missing>"
            ok = ("{{" not in heading) and ("QwenPaw" not in heading) and ("SmartWork" in heading)
            lines.append(f"[{lang}] title='{heading}' | wordmark='{wordmark}' | pass={ok}")

            if lang in ("zh", "en"):
                page.screenshot(path=str(OUT / f"brand_copy_login_{lang}.png"))
            context.close()
        browser.close()
    return lines


if __name__ == "__main__":
    for line in run():
        print(line)
