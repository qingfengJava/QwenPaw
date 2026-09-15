"""壳层几何测量：展开态 / 折叠态，量出缩进、字号、间距、footer、logo 真实值（一次性脚本）。"""

import json
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(r"d:\enterprise_code\xxd\QwenPaw\.qoder")
URL = "http://localhost:5173/workbench"

PROBE = r"""
() => {
  const q = (s, r = document) => r.querySelector(s);
  const box = (e) => { if (!e) return null; const b = e.getBoundingClientRect();
    return { l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top),
             b: Math.round(b.bottom), w: Math.round(b.width), h: Math.round(b.height) }; };
  const css = (e, props) => { if (!e) return null; const c = getComputedStyle(e); const o = {};
    props.forEach((p) => { o[p] = c[p]; }); return o; };
  const row = (e) => { if (!e) return null; const c = getComputedStyle(e);
    const icon = q('.qwenpaw-menu-item-icon, .anticon', e);
    const label = q('.qwenpaw-menu-title-content', e);
    return { box: box(e), padL: c.paddingLeft, padR: c.paddingRight, ml: c.marginLeft,
             mt: c.marginTop, mb: c.marginBottom, fs: c.fontSize, fw: c.fontWeight,
             color: c.color, bg: c.backgroundColor, radius: c.borderTopLeftRadius,
             icon: box(icon), label: box(label),
             inlineStyle: e.getAttribute('style') || '' }; };

  const sider = q('.qwenpaw-layout-sider');
  const children = q('.qwenpaw-layout-sider-children');
  const menus = [...document.querySelectorAll('.qwenpaw-layout-sider .qwenpaw-menu')];
  const topTitles = [...document.querySelectorAll(
      '.qwenpaw-layout-sider > .qwenpaw-layout-sider-children .qwenpaw-menu:not(.qwenpaw-menu-sub) > .qwenpaw-menu-submenu > .qwenpaw-menu-submenu-title')];
  const parent = topTitles.find((t) => t.textContent.includes('员工与通道')) || topTitles[0];
  const subUl = parent ? parent.nextElementSibling : null;
  const child = subUl ? q('.qwenpaw-menu-item', subUl) : null;
  const selected = q('.qwenpaw-menu-item-selected');
  const plainTop = [...document.querySelectorAll(
      '.qwenpaw-menu:not(.qwenpaw-menu-sub) > .qwenpaw-menu-item')][0];
  const arrow = parent ? q('.qwenpaw-menu-submenu-arrow', parent) : null;
  const footer = q('[class*="collapseToggleContainer"]');
  const rail = subUl ? getComputedStyle(subUl, '::before') : null;

  return {
    sider: { box: box(sider), ...css(sider, ['backgroundColor', 'paddingLeft', 'paddingTop']) },
    children: { box: box(children), scrollH: children ? children.scrollHeight : null,
                overflowY: children ? getComputedStyle(children).overflowY : null,
                scrollbarWidth: children ? getComputedStyle(children).scrollbarWidth : null },
    menus: menus.map((m) => ({ box: box(m), cls: m.className.replace(/.*?(qwenpaw-menu[a-z-]*).*$/, '$1'),
               items: m.querySelectorAll('li').length })),
    parentTitle: row(parent),
    childItem: row(child),
    selected: row(selected),
    plainTop: row(plainTop),
    arrow: arrow ? { box: box(arrow), fs: getComputedStyle(arrow).fontSize,
                     color: getComputedStyle(arrow).color, right: getComputedStyle(arrow).insetInlineEnd } : null,
    subRail: rail ? { left: rail.left, w: rail.width, bg: rail.backgroundColor } : null,
    gaps: (() => {
      const out = {};
      if (plainTop && parent) out.topLeafToGroup = Math.round(parent.getBoundingClientRect().top - plainTop.getBoundingClientRect().bottom);
      if (topTitles.length > 1) out.groupToGroup = Math.round(topTitles[1].getBoundingClientRect().top - topTitles[0].getBoundingClientRect().bottom);
      if (subUl && child) out.ulTopToFirstChild = Math.round(child.getBoundingClientRect().top - subUl.getBoundingClientRect().top);
      const kids = subUl ? [...subUl.querySelectorAll('.qwenpaw-menu-item')] : [];
      if (kids.length > 1) out.childToChild = Math.round(kids[1].getBoundingClientRect().top - kids[0].getBoundingClientRect().bottom);
      return out;
    })(),
    footer: footer ? { box: box(footer), bt: getComputedStyle(footer).borderTopWidth,
                       btc: getComputedStyle(footer).borderTopColor,
                       bg: getComputedStyle(footer).backgroundColor,
                       btns: [...footer.querySelectorAll('button')].map((b) => ({ box: box(b), aria: b.getAttribute('aria-label'), title: b.getAttribute('title') })) } : null,
    header: (() => { const h = q('header'); return h ? { box: box(h), ...css(h, ['backgroundColor', 'borderBottomColor']) } : null; })(),
    logo: (() => { const w = q('[class*="logoWrapper"]'); const m = q('[class*="brandMark"]');
      const t = q('[class*="brandText"]'); const v = q('[class*="versionBadge"]');
      const svg = m ? m.querySelector('svg') : null;
      return { wrap: box(w), wrapPadL: w ? getComputedStyle(w).paddingLeft : null,
               wrapW: w ? getComputedStyle(w).width : null,
               mark: box(m), markRadius: m ? getComputedStyle(m).borderTopLeftRadius : null,
               markShadow: m ? getComputedStyle(m).boxShadow.slice(0, 60) : null,
               svg: svg ? { w: svg.getBoundingClientRect().width, vb: svg.getAttribute('viewBox') } : null,
               text: t ? { box: box(t), fs: getComputedStyle(t).fontSize, fw: getComputedStyle(t).fontWeight } : null,
               chip: v ? { box: box(v), radius: getComputedStyle(v).borderTopLeftRadius,
                           role: v.getAttribute('role'), tab: v.getAttribute('tabindex') } : null }; })(),
    headerBtns: [...document.querySelectorAll('header button')].map((b) => ({ box: box(b),
      aria: b.getAttribute('aria-label'), title: b.getAttribute('title'),
      text: (b.textContent || '').trim().slice(0, 12) })),
    navLabels: [...document.querySelectorAll('[class*="navSectionLabel"]')].map((e) => ({
      text: e.textContent, box: box(e), fs: getComputedStyle(e).fontSize,
      fw: getComputedStyle(e).fontWeight, color: getComputedStyle(e).color })),
    headerControls: (() => { const c = q('[class*="headerControls"]'); if (!c) return null;
      return { box: box(c), bg: getComputedStyle(c).backgroundColor,
        radius: getComputedStyle(c).borderTopLeftRadius,
        btns: [...c.querySelectorAll('button')].map((b) => ({ box: box(b), aria: b.getAttribute('aria-label'),
          fs: getComputedStyle(b).fontSize })) }; })(),
    railDividers: document.querySelectorAll('[class*="railDivider"]').length,
    railBtns: [...document.querySelectorAll('[class*="collapsedNavItem"]')].slice(0, 40).map((b) => ({
      box: box(b), aria: b.getAttribute('aria-label') })),
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  };
}
"""


def run(pw, theme, tag, collapse=False):
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="zh-CN")
    page = ctx.new_page()
    page.add_init_script(
        f"try{{localStorage.setItem('qwenpaw-theme','{theme}')}}catch(e){{}}"
    )
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    if collapse:
        page.locator('[class*="collapseToggleContainer"] button').last.click()
        page.wait_for_timeout(700)
    else:
        page.locator(".qwenpaw-menu-submenu-title").first.click()
        page.wait_for_timeout(600)
    data = page.evaluate(PROBE)
    page.screenshot(path=str(OUT / f"measure-{tag}.png"))
    if not collapse:
        page.screenshot(
            path=str(OUT / f"measure-{tag}-rail.png"),
            clip={"x": 0, "y": 0, "width": 260, "height": 620},
        )
    browser.close()
    return data


with sync_playwright() as pw:
    report = {
        "light": run(pw, "light", "light"),
        "dark": run(pw, "dark", "dark"),
        "light-collapsed": run(pw, "light", "light-collapsed", True),
        "dark-collapsed": run(pw, "dark", "dark-collapsed", True),
    }
    (OUT / "shell_measure.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("written")
