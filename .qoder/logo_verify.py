"""品牌标识落地后的真实页面验证截图。

无头 Chromium 依次访问：
- /workbench        顶栏品牌锁定（亮 / 暗）
- /login            登录页品牌锁定（亮 / 暗）
- /                 启动占位徽章（禁用 JS，停在 index.html 静态骨架）

主题通过 localStorage 键 qwenpaw-theme 预设；BrandMark 的 CSS Module 类名为
_badge_xxx，因此用 [class*=badge] 即可直接断言品牌徽章是否真的渲染出来。
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
OUT = Path(__file__).resolve().parent

BRAND_SELECTOR = 'span[class*="badge"]'
HEADER_SELECTOR = '[class*="logoWrapper"]'


def probe(page, url: str) -> dict:
    """访问 url 并统计品牌徽章数量与几何尺寸，返回可读事实。"""
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    marks = page.locator(BRAND_SELECTOR)
    count = marks.count()
    boxes = []
    for i in range(min(count, 4)):
        box = marks.nth(i).bounding_box()
        boxes.append(None if box is None else f'{box["width"]:.0f}x{box["height"]:.0f}')
    return {"url": url, "final": page.url, "count": count, "boxes": boxes}


def shoot(page, name: str, locator_selector: str | None = None) -> str:
    """整页或指定元素截图。"""
    path = str(OUT / name)
    if locator_selector and page.locator(locator_selector).count() > 0:
        page.locator(locator_selector).first.screenshot(path=path)
    else:
        page.screenshot(path=path)
    return name


def mock_auth_enabled(page) -> None:
    """把 /auth/status 的 enabled 改为 true，强制停在登录页。

    本地开发后端默认关闭鉴权，/login 会被 AuthGuard 直接重定向走，
    拦掉这一个接口才能拍到登录页真实的品牌锁定。
    """
    page.route(
        "**/*auth/status*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"enabled": true, "has_users": true, "registration_enabled": false}',
        ),
    )


def run() -> list[str]:
    """跑完全部探测与截图，返回每步事实行。"""
    lines: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for theme in ("light", "dark"):
            context = browser.new_context(
                viewport={"width": 1500, "height": 900},
                device_scale_factor=2,
            )
            context.add_init_script(
                f"localStorage.setItem('qwenpaw-theme', '{theme}');"
            )
            page = context.new_page()

            fact = probe(page, f"{BASE}/workbench")
            lines.append(f"[header:{theme}] {fact}")
            lines.append(shoot(page, f"logo_verify_header_{theme}.png", HEADER_SELECTOR))

            mock_auth_enabled(page)
            fact = probe(page, f"{BASE}/login")
            lines.append(f"[login:{theme}] {fact}")
            lines.append(
                shoot(page, f"logo_verify_login_{theme}.png", 'div[class*="brand"]')
            )

            context.close()

        # 启动占位：关掉 JS，页面会停在 index.html 里的静态骨架，正好拍到徽章
        boot_context = browser.new_context(
            viewport={"width": 1000, "height": 700},
            device_scale_factor=2,
            java_script_enabled=False,
        )
        boot_page = boot_context.new_page()
        boot_page.goto(f"{BASE}/", wait_until="domcontentloaded")
        boot_page.wait_for_timeout(500)
        boot_marks = boot_page.locator(".qwenpaw-boot__badge")
        lines.append(f"[boot] badge_count={boot_marks.count()}")
        if boot_marks.count() > 0:
            boot_marks.screenshot(path=str(OUT / "logo_verify_boot.png"))
        else:
            boot_page.screenshot(path=str(OUT / "logo_verify_boot.png"))
        lines.append("logo_verify_boot.png")
        boot_context.close()

        browser.close()
    return lines


if __name__ == "__main__":
    for line in run():
        print(line)
