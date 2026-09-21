"""Exercise journal creation safety and grouped ledger in the synthetic browser fixture."""

from __future__ import annotations

import os
from collections.abc import Sequence
from playwright.sync_api import expect

from smoke_transactions import (
    PASSWORD, VIEWPORTS, Page, SmokeCheckFailure, assert_no_page_overflow,
    open_sidebar_for_narrow_view, parse_args, run_smoke_check,
)


def check_journal_viewport(page: Page, url: str, viewport: tuple[int, int]) -> None:
    # Glide renders to canvas, without DOM rows. Observe actual paint calls in
    # this synthetic fixture so the no-sort check cannot pass vacuously.
    page.add_init_script("""(() => {
      window.journalRowTypes = {};
      window.journalHeaders = {};
      const original = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function(text, x, y, ...rest) {
        if (this.canvas.closest('.st-key-transactions_ledger_surface')) {
          if (text === 'Journal' || text === '↳ Posting') window.journalRowTypes[Math.round(y)] = text;
          if (y < 36 && ['Date','Type','Account','Amount','Debit','Credit'].includes(text)) {
            window.journalHeaders[text] = {x, y};
          }
        }
        return original.call(this, text, x, y, ...rest);
      };
    })();""")
    page.goto(url)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("heading", name="Your books at a glance", exact=True).wait_for()
    open_sidebar_for_narrow_view(page, viewport[0])
    route = page.get_by_role("radio", name="Transactions", exact=True)
    route.evaluate("element => element.click()")
    page.get_by_role("heading", name="Transactions", exact=True).wait_for()
    page.get_by_role("tab", name="Add transaction", exact=True).click()
    entry_modes = page.get_by_role("radiogroup", name="Entry Type", exact=True)
    entry_modes.wait_for()
    page.get_by_label("Amount", exact=True).first.fill("12.34")
    entry_modes.get_by_text("Multi-line Journal", exact=True).click()
    page.get_by_role("button", name="Keep editing", exact=True).wait_for()
    page.get_by_role("button", name="Keep editing", exact=True).click()
    if page.get_by_label("Amount", exact=True).first.input_value() != "12.34":
        raise SmokeCheckFailure("Canceling the mode switch lost the simple draft amount")
    entry_modes.get_by_text("Multi-line Journal", exact=True).click()
    page.get_by_role("button", name="Discard and switch to Multi-line Journal", exact=True).click()
    page.get_by_role("button", name="+ Add line", exact=True).wait_for()
    add_surface = page.locator('.st-key-transactions_add_surface')
    expect(add_surface.get_by_role("button", name="Remove", exact=True)).to_have_count(2)
    page.get_by_role("button", name="+ Add line", exact=True).click()
    expect(add_surface.get_by_role("button", name="Remove", exact=True)).to_have_count(3)
    add_surface.get_by_role("button", name="Remove", exact=True).last.click()
    expect(add_surface.get_by_role("button", name="Remove", exact=True)).to_have_count(2)
    page.get_by_role("button", name="Save journal entry", exact=True).wait_for()
    assert_no_page_overflow(page)
    page.get_by_role("tab", name="View & edit ledger", exact=True).click()
    page.get_by_label("Search transactions", exact=True).fill("Viewport journal")
    page.get_by_label("Search transactions", exact=True).press("Enter")
    page.get_by_text("Showing 1 entry(s).", exact=True).wait_for()
    grid = page.locator('.st-key-transactions_ledger_surface [data-testid="stDataFrame"]').first
    grid.wait_for()
    canvas = grid.locator('canvas[data-testid="data-grid-canvas"]')
    canvas.scroll_into_view_if_needed()
    page.wait_for_function("Object.values(window.journalRowTypes).filter(x => x === '↳ Posting').length === 3")
    before = page.evaluate("Object.entries(window.journalRowTypes).sort((a,b) => Number(a[0])-Number(b[0])).map(x => x[1])")
    if before != ["Journal", "↳ Posting", "↳ Posting", "↳ Posting"]:
        raise SmokeCheckFailure(f"Unexpected painted journal row order: {before}")
    headers = page.evaluate("window.journalHeaders")
    if "Type" not in headers:
        raise SmokeCheckFailure("The grouped ledger header was not painted")
    for header in headers.values():
        box = canvas.bounding_box()
        if box is None or header["x"] >= box["width"] - 10:
            continue
        canvas.click(position={"x": header["x"] + 3, "y": 18}, force=True)
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        after = page.evaluate("Object.entries(window.journalRowTypes).sort((a,b) => Number(a[0])-Number(b[0])).map(x => x[1])")
        if after != before:
            raise SmokeCheckFailure("A dataframe header changed grouped posting order")
    assert_no_page_overflow(page)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    os.environ["TABULA_RASA_SMOKE_JOURNALS"] = "1"
    try:
        failures = run_smoke_check(args.screenshots_dir, args.port, page_check=check_journal_viewport)
    except SmokeCheckFailure as error:
        print(f"Journal smoke check failed: {error}")
        return 1
    if failures:
        print("Journal viewport smoke check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Journal viewport smoke check passed at " + ", ".join(f"{w}x{h}" for w, h in VIEWPORTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
