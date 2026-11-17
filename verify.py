#!/usr/bin/env python3
"""
verify.py — headless QA for a generated report. Run it before delivering, every time.

    python verify.py relatorio.html                 # screenshots next to the file
    python verify.py relatorio.html --out shots/ --pdf

Checks
    • zero console errors / page errors / failed requests
    • every <figure.chart> rendered (data-rendered="1") and actually drew something
    • no horizontal overflow on mobile (390 px)
    • cross-filter: clicking a bar, a dropdown checkbox and a date preset changes state + KPIs;
      chips appear; "Limpar filtros" resets; clicking a Plot mark (scatter/heatmap/dumbbell/ci/drivers) filters
    • survey reports: the browser's CSAT/CES/NPS values and CIs equal the Python ones (spec["checks"]),
      Likert / NPS / theme rows filter on click, tooltips carry the CI, small groups are flagged (never hidden)
    • table: search narrows rows, header click sorts, CSV download fires
    • theme toggle switches to dark and charts re-render without errors
Outputs
    <name>-desktop-light.png, <name>-desktop-dark.png, <name>-mobile.png (full page)
    <name>-hero-light.png / -hero-dark.png (first viewport, good for chat previews)
    <name>.pdf with --pdf (print stylesheet)
Exit code 1 if anything failed. Requires: pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--out")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--locale", default="pt-BR", help="browser locale (affects native date inputs)")
    a = ap.parse_args()
    html = Path(a.html).resolve()
    out = Path(a.out).resolve() if a.out else html.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = html.stem
    url = html.as_uri()
    problems: list[str] = []
    log: list[str] = []

    def ok(cond, msg):
        (log if cond else problems).append(("✓ " if cond else "✗ ") + msg)
        return cond

    # build-time rule: a chart without data is omitted (warning), and a section left without charts goes with its TOC entry
    try:
        import importlib.util
        bs = importlib.util.spec_from_file_location("kit_build_v", Path(__file__).resolve().parent / "build.py")
        bm = importlib.util.module_from_spec(bs); bs.loader.exec_module(bm)
        t = {"fields": {"dims": [{"key": "a"}, {"key": "z"}], "measures": [{"key": "v", "format": "number"}, {"key": "w", "format": "number"}]},
             "kpis": [{"measure": "v"}, {"measure": "w"}],
             "sections": [{"id": "s1", "charts": [{"type": "bars", "dim": "a", "measure": "v"}, {"type": "bars", "dim": "a", "measure": "w"}]},
                          {"id": "s2", "charts": [{"type": "bars", "dim": "z", "measure": "v"}]}],
             "data": [{"a": "x", "z": None, "v": 1, "w": None}, {"a": "y", "z": None, "v": 2, "w": None}]}
        w = bm.prune_empty(t, bm._columns(t))
        okb = [len(s_["charts"]) for s_ in t["sections"]] == [1] and len(t["kpis"]) == 1 and len(w) == 4
        (log if okb else problems).append(("✓ " if okb else "✗ ") + f"build omits charts/sections/KPIs without data ({len(w)} warnings)")
    except Exception as e:  # noqa: BLE001
        problems.append(f"✗ build empty-chart rule could not be checked: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def open_page(**ctx):
            context = browser.new_context(**ctx, accept_downloads=True, locale=a.locale)
            page = context.new_page()
            errs: list[str] = []
            page.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
            page.on("requestfailed", lambda r: errs.append(f"requestfailed: {r.url[:120]}"))
            page.add_init_script("try{localStorage.clear()}catch(e){}")
            page.goto(url)
            page.wait_for_function("window.__report && window.__report.ready", timeout=30000)
            page.wait_for_timeout(1700)   # let the hero intro settle (1.1 s) before the first screenshot
            return context, page, errs

        def full_shot(page, path):
            """full-page capture with every scroll reveal in its final state"""
            page.emulate_media(reduced_motion="reduce")
            page.evaluate("window.__report.revealAll()")
            page.wait_for_timeout(150)
            page.screenshot(path=path, full_page=True)
            page.emulate_media(reduced_motion="no-preference")

        def charts_ok(page, label):
            res = page.evaluate("""() => [...document.querySelectorAll('figure.chart')].map(f => ({
                id: f.dataset.chart, type: f.dataset.type, r: f.dataset.rendered,
                drew: !!f.querySelector('.viz svg, .viz .bar, .viz .col, .viz .seg-s, .viz .multiple, .viz .lk-row, .viz .np-row, .viz .th-row') || !!f.querySelector('.viz .empty:not(:has(*))'),
                err: (f.querySelector('.viz .empty')?.textContent || '').includes('⚠') }))""")
            bad = [r for r in res if r["r"] != "1" or not r["drew"] or r["err"]]
            ok(not bad, f"{label}: {len(res)} charts rendered" + (f" — failing: {bad}" if bad else ""))
            return res

        # ---------------- desktop light: render + interactions
        ctx, page, errs = open_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme="light")
        charts_ok(page, "desktop light")
        page.screenshot(path=str(out / f"{stem}-hero-light.png"))
        # motion: charts below the fold wait for the scroll; the first bar list animates in when reached
        pend = page.evaluate("[...document.querySelectorAll('figure.chart')].filter(f => !f.classList.contains('in')).length")
        ok(pend > 0, f"scroll reveal: {pend} charts wait below the fold")
        first_list = page.locator(".bars, .lk, .np").first
        if first_list.count():
            first_list.scroll_into_view_if_needed()
            page.wait_for_timeout(1600)
            grown = page.evaluate("(() => { const f = document.querySelector('.bars .fill, .lk .lk-side, .np .np-bar i'); return f && f.closest('.chart').classList.contains('in') && f.getBoundingClientRect().width > 4; })()")
            ok(bool(grown), "scroll reveal: first bar list grew in on scroll")
        page.mouse.wheel(0, -400); page.wait_for_timeout(300)
        full_shot(page, str(out / f"{stem}-desktop-light.png"))

        st0 = page.evaluate("window.__report.state")
        kpi0 = page.evaluate("[...document.querySelectorAll('.kpi .value')].map(e=>e.textContent)")
        ok(bool(kpi0), f"KPIs present: {kpi0}")

        # 0) survey stats: browser == Python (ratio-of-sums + same CI formulas)
        checks = page.evaluate("window.__report.checks")
        if checks and checks.get("values"):
            bad = []
            for k, exp in checks["values"].items():
                got = page.evaluate(f"window.__report.stat({json.dumps(k)})")
                for f in ("v", "lo", "hi", "n"):
                    e, g = exp.get(f), (got or {}).get(f)
                    if e is None and g is None:
                        continue
                    if e is None or g is None or abs(e - g) > 1e-9 * max(1, abs(e)) + 1e-12:
                        bad.append(f"{k}.{f}: python {e} vs browser {g}")
            ok(not bad, f"survey stats match Python for {len(checks['values'])} metrics (value, CI, n)" + (f" — {bad[:4]}" if bad else ""))
            n_small = page.evaluate("document.querySelectorAll('.small-badge, .viz .small, #t tr.small').length + [...document.querySelectorAll('.viz svg text')].filter(t => t.textContent.includes('◌')).length")
            ok(n_small > 0, f"small samples shown and flagged ({n_small} marks), not hidden")
            kci = page.evaluate("[...document.querySelectorAll('.kpi .kci')].map(e => e.textContent.trim())")
            ok(bool(kci) and all("IC" in t for t in kci), f"KPI cards show CI + n ({kci[:2]})")
            for sel, hov, name in [(".lk-row:not(.all)", ".lk-side.pos > *", "Likert row"), (".np-row:not(.all)", None, "NPS row"), (".th-main", None, "comment theme")]:
                loc = page.locator(sel)
                if not loc.count():
                    continue
                el = loc.first
                el.scroll_into_view_if_needed()
                (el.locator(hov).first if hov else el).hover(); page.wait_for_timeout(150)
                tip = page.evaluate("(document.querySelector('#tt')||{}).textContent || ''")
                ok("IC" in tip or "amostra" in tip or "%" in tip, f"{name} tooltip: {tip[:90]!r}")
                el.click(); page.wait_for_timeout(200)
                st = page.evaluate("window.__report.state")
                ok(bool(st["cats"]) and st["rows"] < st0["rows"], f"{name} click filters ({st['cats']}, {st0['rows']} → {st['rows']} rows)")
                charts_ok(page, f"after {name} filter")
                page.evaluate("window.__report.reset()"); page.wait_for_timeout(150)

        # 1) click-to-filter on an HTML bar
        bar = page.locator(".bars .bar:not(.other)").first
        if bar.count():
            label = bar.locator(".lbl").inner_text()
            bar.click()
            page.wait_for_timeout(200)
            st1 = page.evaluate("window.__report.state")
            kpi1 = page.evaluate("[...document.querySelectorAll('.kpi .value')].map(e=>e.textContent)")
            ok(st1["rows"] < st0["rows"] and any(label in v for v in st1["cats"].values()), f"bar click filters ('{label}': {st0['rows']} → {st1['rows']} rows)")
            ok(kpi1 != kpi0, "KPIs change after bar filter")
            ok(page.locator("#chips .chip").count() >= 1, "filter chip shown")
            charts_ok(page, "after bar filter")
            page.locator("#clear-all").click()
            page.wait_for_timeout(200)
            ok(page.evaluate("window.__report.state")["rows"] == st0["rows"], "'Limpar filtros' resets")

        # 2) dropdown multi-select
        dd = page.locator(".dd:not(.daterange)").first
        if dd.count():
            dd.locator("> button").click()
            page.wait_for_timeout(150)
            dd.locator(".opts label").nth(1).click()
            page.wait_for_timeout(200)
            st2 = page.evaluate("window.__report.state")
            ok(sum(len(v) for v in st2["cats"].values()) == 1 and st2["rows"] < st0["rows"], f"dropdown filter works ({st2['cats']})")
            page.mouse.click(5, 5)
            page.evaluate("window.__report.reset()")

        # 3) date preset
        presets = page.locator("#presets button")
        if presets.count() > 1:
            target = presets.nth(presets.count() - 1)
            target.click()
            page.wait_for_timeout(200)
            st3 = page.evaluate("window.__report.state")
            ok(st3["range"] != st0["range"], f"date preset changes range ({st0['range']} → {st3['range']})")
            charts_ok(page, "after date preset")
            page.evaluate("window.__report.reset()")

        # 3b) custom date range via the popover
        if page.locator(".dd.daterange").count():
            page.locator(".dd.daterange > button").click()
            mx = st0["range"][1]
            page.fill("#d-from", mx[:8] + "01")
            page.fill("#d-to", mx)
            page.locator(".dd.daterange .apply").click()
            page.wait_for_timeout(200)
            st5 = page.evaluate("window.__report.state")
            ok(st5["range"] == [mx[:8] + "01", mx], f"custom date range applies ({st5['range']})")
            charts_ok(page, "after custom range")
            page.evaluate("window.__report.reset()")

        # 4) click a Plot mark (scatter dot / heatmap cell / dumbbell row)
        for sel in ["figure[data-type=scatter] svg g[aria-label=dot] circle", "figure[data-type=heatmap] svg g[aria-label=cell] rect",
                    "figure[data-type=dumbbell] svg g[aria-label=dot] circle", "figure[data-type=ci] svg g[aria-label=dot] circle",
                    "figure[data-type=drivers] svg g[aria-label=bar] rect"]:
            loc = page.locator(sel)
            if not loc.count():
                continue
            el = loc.nth(min(2, loc.count() - 1))
            el.scroll_into_view_if_needed()
            box = el.bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(120)
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(200)
            st4 = page.evaluate("window.__report.state")
            ok(bool(st4["cats"]), f"click on Plot mark filters ({sel.split()[0]} → {st4['cats']})")
            page.evaluate("window.__report.reset()")

        # 5) table: search, sort, csv
        page.locator("#t-search").scroll_into_view_if_needed()
        n_before = page.locator("#pager").inner_text()
        first_cell = page.locator("#t tbody tr td").first.inner_text() if page.locator("#t tbody tr").count() else ""
        if first_cell:
            page.locator("#t-search").fill(first_cell[:3])
            page.wait_for_timeout(150)
            ok(page.locator("#t tbody tr").count() >= 1, f"table search returns rows for '{first_cell[:3]}'")
            page.locator("#t-search").fill("")
        th = page.locator("#t thead th").nth(1)
        th.click(); page.wait_for_timeout(100)
        ok("sorted" in (th.get_attribute("class") or ""), "table header sorts")
        with page.expect_download(timeout=5000) as dl:
            page.locator("#t-csv").click()
        ok(dl.value.suggested_filename.endswith(".csv"), f"CSV download ({dl.value.suggested_filename})")
        ok(bool(n_before), f"pager: {n_before}")

        # 5b) Passo 0 context: the "about" column appears only when contexto.exibir is true
        ctxs = page.evaluate("window.__report.contexto")
        if ctxs is not None:
            want = bool(ctxs.get("exibir"))
            ok((page.locator("#method .about").count() > 0) == want,
               f"contexto in footer {'shown' if want else 'hidden'} (exibir: {str(want).lower()})")

        # 5c) methodology: last block, collapsed by default, opens/closes with the summary, print expands it
        acc = page.evaluate("""(() => { const d = document.querySelector('#method-acc'); if (!d) return null;
            const blocks = [...document.querySelectorAll('main > section, #sections > section, #table-section, #method')];
            return { open: d.open, last: blocks[blocks.length - 1]?.id, summary: !!d.querySelector('summary') }; })()""")
        ok(bool(acc) and acc["summary"] and not acc["open"] and acc["last"] == "method", f"methodology is last and collapsed by default ({acc})")
        if acc:
            page.locator("#method-acc summary").scroll_into_view_if_needed()
            page.locator("#method-acc summary").click(); page.wait_for_timeout(900)
            h_open = page.evaluate("(() => { const d = document.querySelector('#method-acc'); return d.open ? d.querySelector('.acc-body').getBoundingClientRect().height : 0; })()")
            page.locator("#method-acc summary").click(); page.wait_for_timeout(900)
            closed = page.evaluate("!document.querySelector('#method-acc').open")
            page.evaluate("window.__report.preparePrint()")
            printed = page.evaluate("document.querySelector('#method-acc').open")
            page.evaluate("window.__report.endPrint()"); page.wait_for_timeout(200)
            after = page.evaluate("!document.querySelector('#method-acc').open")
            ok(h_open > 40 and closed and printed and after, f"methodology accordion: opens ({h_open:.0f}px), closes, expands for print, re-collapses")

        # 5d) ONE place for interaction help: no per-chart "click to filter" lines
        per_chart = page.evaluate(r"""[...document.querySelectorAll('figure.chart')].filter(f => /clique para filtrar|shift\s*\+\s*clique|click to filter|shift\s*\+\s*click/i.test(f.textContent)).map(f => f.dataset.chart)""")
        n_help = page.locator("#btn-help").count()
        ok(not per_chart and n_help == 1, f"interaction help in one place (help button: {n_help}; per-chart repeats: {per_chart or 'none'})")
        page.locator("#btn-help").click(); page.wait_for_timeout(300)
        ok(page.evaluate("document.querySelector('#help-pop').classList.contains('on')"), "help popover opens")
        page.keyboard.press("Escape"); page.wait_for_timeout(200)

        # 5e) one time grain for every time chart (unless grainOverride)
        g = page.evaluate("window.__report.grain()")
        cg = page.evaluate("window.__report.chartGrains()")
        off = [c for c in cg if c["grain"] != g and not c["override"]]
        ok(not off, f"single time grain '{g}' across {len(cg)} time charts" + (f" — different: {off}" if off else ""))

        # 5f) survey questions: verbatim from the data, never truncated
        qs = page.evaluate("window.__report.questions()")
        if qs:
            bad = [q for q in qs if q["shown"] != q["expected"]]
            cut = page.evaluate("""[...document.querySelectorAll('p.question')].filter(p => { const s = getComputedStyle(p);
                return p.scrollWidth > p.clientWidth + 1 || s.textOverflow === 'ellipsis' || s.webkitLineClamp !== 'none' && s.webkitLineClamp !== '' || p.textContent.trim().endsWith('…'); }).length""")
            ok(not bad and not cut, f"{len(qs)} survey questions shown in full, verbatim (mismatch: {len(bad)}, truncated: {cut})")
            trunc = page.evaluate("""[...document.querySelectorAll('.viz svg text, .viz .lbl')].filter(t => t.textContent.trim().endsWith('…')).map(t => t.textContent).slice(0, 5)""")
            ok(not trunc, f"no chart label cut with '…' ({trunc or 'none'})")

        # 5g) charts with no data: a filter that empties everything collapses each chart to one quiet line (no empty boxes)
        if page.evaluate("!!window.__report.state.range"):
            page.evaluate("window.__report.setRange('1901-01-01', '1901-01-31')"); page.wait_for_timeout(300)
            emp = page.evaluate("""[...document.querySelectorAll('figure.chart')].map(f => ({ id: f.dataset.chart, e: f.classList.contains('is-empty'),
                h: f.querySelector('.viz').getBoundingClientRect().height, svg: !!f.querySelector('.viz svg') }))""")
            bad = [e for e in emp if not e["e"] or e["h"] > 60 or e["svg"]]
            ok(not bad, f"empty charts collapse to one line under a filter with no data ({len(emp)} charts)" + (f" — {bad[:3]}" if bad else ""))
            page.evaluate("window.__report.reset()"); page.wait_for_timeout(300)
            back = page.evaluate("document.querySelectorAll('figure.chart.is-empty').length")
            ok(back == 0, f"charts come back after the filter is cleared ({back} still empty)")
        n_sec = page.evaluate("document.querySelectorAll('#sections > section').length")
        n_toc = page.evaluate("document.querySelectorAll('#toc a[data-t]').length")
        ok(n_toc == n_sec + page.evaluate("document.querySelectorAll('#table-section, #method').length"), f"TOC matches the sections on the page ({n_toc} entries)")

        # 6) theme toggle → dark
        page.evaluate("window.scrollTo(0,0)")
        page.locator("#btn-theme").click()
        page.wait_for_timeout(350)
        ok(page.evaluate("document.documentElement.dataset.theme") == "dark", "theme toggle → dark")
        charts_ok(page, "desktop dark")
        page.screenshot(path=str(out / f"{stem}-hero-dark.png"))
        full_shot(page, str(out / f"{stem}-desktop-dark.png"))
        ok(not errs, "desktop: no console/page errors" + (f" — {errs[:5]}" if errs else ""))

        if a.pdf:
            page.evaluate("window.__report.preparePrint()")
            page.emulate_media(media="print")
            page.pdf(path=str(out / f"{stem}.pdf"), format="A4", print_background=True)
            log.append(f"✓ PDF → {out / (stem + '.pdf')}")
        ctx.close()

        # ---------------- mobile
        ctx, page, errs = open_page(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True, color_scheme="light", reduced_motion="reduce")
        charts_ok(page, "mobile")
        rm = page.evaluate("[...document.querySelectorAll('figure.chart')].every(f => f.classList.contains('in')) && [...document.querySelectorAll('.kpi .value')].every(v => /[1-9]/.test(v.textContent))")
        ok(bool(rm), "prefers-reduced-motion: everything rendered in its final state")
        overflow = page.evaluate("Math.max(document.documentElement.scrollWidth, window.innerWidth) - visualViewport.width")   # layout viewport must stay at device width
        ok(overflow <= 1, f"mobile: no horizontal overflow ({overflow}px)")
        page.screenshot(path=str(out / f"{stem}-mobile.png"), full_page=True)
        page.screenshot(path=str(out / f"{stem}-hero-mobile.png"))
        ok(not errs, "mobile: no console/page errors" + (f" — {errs[:5]}" if errs else ""))
        ctx.close()
        browser.close()

    print("\n".join(log + problems))
    print(json.dumps({"passed": len(log), "failed": len(problems), "screenshots": str(out)}, ensure_ascii=False))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
