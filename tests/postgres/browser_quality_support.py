"""Bounded browser-quality checks; all data comes from disposable fixtures."""

from pathlib import Path

from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[2]
AXE = ROOT / 'web/node_modules/axe-core/axe.min.js'
VIEWPORTS = [(1440, 1000), (1200, 900), (900, 900), (390, 844), (320, 844)]


def assert_accessible(page):
    assert AXE.is_file(), 'Run npm --prefix web ci to install the pinned accessibility engine.'
    page.add_script_tag(path=str(AXE))
    violations = page.evaluate("""async () => (await axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] }
    })).violations.map(rule => ({ id: rule.id, impact: rule.impact,
        targets: rule.nodes.map(node => node.target), help: rule.helpUrl }))""")
    assert not violations, violations
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth'), 'Page overflow'


def assert_dialog_keyboard(page, title, keep_label, confirm_label, opener):
    dialog = page.get_by_role('alertdialog', name=title, exact=True)
    expect(dialog).to_be_visible()
    keep = dialog.get_by_role('button', name=keep_label, exact=True)
    confirm = dialog.get_by_role('button', name=confirm_label, exact=True)
    expect(keep).to_be_focused()
    expect(dialog).to_have_attribute('aria-modal', 'true')
    assert_accessible(page)
    page.keyboard.press('Shift+Tab')
    expect(confirm).to_be_focused()
    page.keyboard.press('Tab')
    expect(keep).to_be_focused()
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(opener).to_be_focused()
