"""把 logo 方向对比页渲染成 PNG，供方案评审查看。

无头 Chromium 打开本地 HTML，按整页与单卡片两种粒度截图。
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "logo_directions.html"
CARDS = {
    "base": "现状",
    "a_crew": "方向 A",
    "b_badge": "方向 B",
    "c_tie": "方向 C",
    "d_pixel": "方向 D",
    "wordmark": "附加",
}


def shoot() -> list[str]:
    """渲染并截图，返回落盘文件名列表。"""
    written: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=2)
        page.goto(SOURCE.as_uri())
        page.wait_for_timeout(400)

        full = ROOT / "logo_directions_full.png"
        page.screenshot(path=str(full), full_page=True)
        written.append(full.name)

        cards = page.locator(".card")
        count = cards.count()
        for index in range(count):
            card = cards.nth(index)
            head = card.locator(".tag").inner_text()
            key = next((k for k, v in CARDS.items() if v in head), f"card{index}")
            out = ROOT / f"logo_card_{key}.png"
            card.screenshot(path=str(out))
            written.append(out.name)

        browser.close()
    return written


if __name__ == "__main__":
    for name in shoot():
        print(name)
