"""壳层（顶标 + 侧栏）改版验证：亮/暗 × 展开/折叠 截图 + 状态探针（一次性脚本）。"""

import json
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(r"d:\enterprise_code\xxd\QwenPaw\.qoder")
URL = "http://localhost:5173/workbench"

PROBE = """
() => {
  const q = (s) => document.querySelector(s);
  const all = (s) => [...document.querySelectorAll(s)];
  const sel = q('.qwenpaw-menu-item-selected');
  const plain = all('.qwenpaw-menu-item').find((e) => !e.className.includes('selected'));
  const selLabel = sel && sel.querySelector('.qwenpaw-menu-title-content');
  const plainLabel = plain && plain.querySelector('.qwenpaw-menu-title-content');
  const group = q('.qwenpaw-menu-submenu-selected > .qwenpaw-menu-submenu-title');
  const rail = q('.qwenpaw-menu-sub.qwenpaw-menu-inline');
  const mark = q('[class*="brandMark"]');
  const chip = q('[class*="versionBadge"]');
  return {
    brandMark: mark
      ? {
          w: Math.round(mark.getBoundingClientRect().width),
          bg: getComputedStyle(mark).backgroundImage.slice(0, 46),
          radius: getComputedStyle(mark).borderTopLeftRadius,
          hasSvg: !!mark.querySelector('svg'),
        }
      : null,
    brandText: q('[class*="brandText"]') ? q('[class*="brandText"]').textContent : null,
    brandTextSize: q('[class*="brandText"]')
      ? getComputedStyle(q('[class*="brandText"]')).fontSize
      : null,
    versionChip: chip
      ? { bg: getComputedStyle(chip).backgroundColor, color: getComputedStyle(chip).color,
          border: getComputedStyle(chip).borderTopColor, family: getComputedStyle(chip).fontFamily.slice(0, 22) }
      : null,
    header: (() => { const h = q('header'); const c = getComputedStyle(h);
      return { h: Math.round(h.getBoundingClientRect().height), bg: c.backgroundColor, border: c.borderBottomColor }; })(),
    sider: (() => { const s = q('.qwenpaw-layout-sider'); if (!s) return null; const c = getComputedStyle(s);
      return { w: Math.round(s.getBoundingClientRect().width), bg: c.backgroundColor, padTop: c.paddingTop }; })(),
    selected: sel
      ? {
          bg: getComputedStyle(sel).backgroundColor,
          color: getComputedStyle(sel).color,
          justify: getComputedStyle(sel).justifyContent,
          weight: getComputedStyle(sel).fontWeight,
          labelLeft: selLabel ? Math.round(selLabel.getBoundingClientRect().left) : null,
          plainLabelLeft: plainLabel ? Math.round(plainLabel.getBoundingClientRect().left) : null,
          bar: (() => { const b = getComputedStyle(sel, '::before');
            return { w: b.width, h: b.height, bg: b.backgroundImage.slice(0, 46) }; })(),
        }
      : null,
    groupTitleColor: group ? getComputedStyle(group).color : null,
    submenuRail: rail ? getComputedStyle(rail, '::before').width + ' / ' + getComputedStyle(rail, '::before').backgroundColor : null,
    itemHeight: plain ? Math.round(plain.getBoundingClientRect().height) : null,
    itemRadius: plain ? getComputedStyle(plain).borderTopLeftRadius : null,
    itemColor: plain ? getComputedStyle(plain).color : null,
    hoverBg: plain ? getComputedStyle(plain).backgroundColor : null,
    collapsedActive: (() => { const e = q('[class*="collapsedNavItemActive"]'); if (!e) return null;
      const c = getComputedStyle(e); return { bg: c.backgroundColor, color: c.color, radius: c.borderTopLeftRadius }; })(),
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  };
}
"""


def run(pw, theme: str, tag: str, collapse: bool = False):
    browser = pw.chromium.launch()
    ctx = browser.new_context(
        viewport={"width": 1600, "height": 1000},
        device_scale_factor=1,
        locale="zh-CN",
    )
    page = ctx.new_page()
    logs: list[str] = []
    page.on(
        "console",
        lambda m: logs.append(f"{m.type}: {m.text}")
        if m.type in ("error", "warning")
        else None,
    )
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    page.add_init_script(
        f"try{{localStorage.setItem('qwenpaw-theme','{theme}')}}catch(e){{}}"
    )
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    if collapse:
        # 底部栏最后一个按钮 = 折叠/展开
        page.locator('[class*="collapseToggleContainer"] button').last.click()
        page.wait_for_timeout(700)
    else:
        # 展开首个手风琴组，否则子项不在 DOM 里，量不到 hover/选中/引导线
        page.locator('.qwenpaw-menu-submenu-title').first.click()
        page.wait_for_timeout(600)
    data = page.evaluate(PROBE)
    page.screenshot(path=str(OUT / f"verify-shell-{tag}.png"))
    if not collapse:
        page.screenshot(
            path=str(OUT / f"verify-shell-{tag}-rail.png"),
            clip={"x": 0, "y": 0, "width": 300, "height": 780},
        )
    browser.close()
    keep = [e for e in logs if "DevTools" not in e and "forwardRef" not in e and "Spin" not in e]
    return data, keep[:6]


with sync_playwright() as pw:
    report = {}
    for theme, tag, do_collapse in (
        ("light", "light", False),
        ("dark", "dark", False),
        ("light", "light-collapsed", True),
        ("dark", "dark-collapsed", True),
    ):
        data, logs = run(pw, theme, tag, do_collapse)
        report[tag] = {"probe": data, "console": logs}
    (OUT / "shell_verify.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("written")
