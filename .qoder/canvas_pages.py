"""壳层画布跨页检查：非工作台页面（白卡片）在渐变壳层下是否协调（一次性脚本）。"""

import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(r"d:\enterprise_code\xxd\QwenPaw\.qoder")

PAGES = [
    ("models", "http://localhost:5173/models"),
    ("chat", "http://localhost:5173/chat"),
]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for tag, url in PAGES:
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1000}, locale="zh-CN"
        )
        page = ctx.new_page()
        page.add_init_script(
            "try{localStorage.setItem('qwenpaw-theme','light')}catch(e){}"
        )
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(1600)
        info = page.evaluate(
            """() => {
  const q = (s) => document.querySelector(s);
  const px = (e) => { if (!e) return null; const b = e.getBoundingClientRect();
    return { l: Math.round(b.left), t: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) }; };
  const card = q('.page-content');
  const samples = {};
  if (card) {
    const c = getComputedStyle(card);
    samples.cardBg = c.backgroundColor;
    samples.cardRadius = c.borderTopLeftRadius;
  }
  const layout = q('.qwenpaw-layout-content');
  samples.contentBg = layout ? getComputedStyle(layout).backgroundColor : null;
  const inner = q('.qwenpaw-layout > .qwenpaw-layout');
  samples.innerLayoutBg = inner ? getComputedStyle(inner).backgroundColor : null;
  return { samples, card: px(card),
           overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
           hasHScroll: !!q('.page-content') && q('.page-content').scrollWidth > q('.page-content').clientWidth };
}"""
        )
        print(tag, info)
        page.screenshot(path=str(OUT / f"canvas-{tag}.png"))
        ctx.close()
    browser.close()
