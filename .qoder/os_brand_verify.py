"""桌面 OS 子品牌名的真实渲染验证。

访问 /os，分别读取：
- 启动页与桌面水印的品牌文字（按可见文本 "SmartWork OS" 定位）
- 菜单栏品牌按钮的 aria-label（按包含吉祥物图的 button 定位）

逐语言执行，确认产品名来自常量与 {{brand}} 插值，无 QwenPaw 残留、无 {{ 字面量。
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
OUT = Path(__file__).resolve().parent
LANGS = ["zh", "en"]


def run() -> list[str]:
    """逐语言进 /os 读取三处品牌文字，返回校验事实行。"""
    lines: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for lang in LANGS:
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=2,
            )
            context.add_init_script(
                "localStorage.setItem('qwenpaw-theme','dark');"
                f"localStorage.setItem('language', '{lang}');"
            )
            page = context.new_page()
            page.goto(f"{BASE}/os", wait_until="domcontentloaded")

            # 启动页 2s + 淡出 0.4s；OS 样式是 antd-style（类名为 hash，不能靠类名选），
            # 因此按可见文本与元素定位取证
            page.wait_for_timeout(700)
            brand_texts = page.locator("text=SmartWork OS")
            boot_text = (
                brand_texts.nth(0).inner_text().strip() if brand_texts.count() else "<missing>"
            )
            page.screenshot(path=str(OUT / f"os_brand_boot_{lang}.png"))

            page.wait_for_timeout(3000)
            after_texts = page.locator("text=SmartWork OS")
            watermark_text = "/".join(
                after_texts.nth(i).inner_text().strip() for i in range(after_texts.count())
            ) or "<missing>"
            menubar = page.locator('button:has(img[src="/qwenpaw.png"])')
            menu_label = (
                menubar.first.get_attribute("aria-label") if menubar.count() else "<missing>"
            )
            page.screenshot(path=str(OUT / f"os_brand_desktop_{lang}.png"))

            joined = f"{boot_text}|{watermark_text}|{menu_label}"
            ok = "SmartWork" in joined and "QwenPaw" not in joined and "{{" not in joined
            lines.append(
                f"[{lang}] brandText='{boot_text}' watermarkOrCount='{watermark_text}' "
                f"menuLabel='{menu_label}' pass={ok}"
            )
            context.close()
        browser.close()
    return lines


if __name__ == "__main__":
    for line in run():
        print(line)
