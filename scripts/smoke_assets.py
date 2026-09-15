"""Run the opt-in Assets viewport smoke check."""

from __future__ import annotations

from collections.abc import Sequence

from smoke_transactions import (
    PASSWORD,
    VIEWPORTS,
    Page,
    SmokeCheckFailure,
    assert_no_page_overflow,
    open_sidebar_for_narrow_view,
    parse_args,
    require_input,
    run_smoke_check,
)


def check_assets_viewport(
    page: Page, url: str, viewport: tuple[int, int]
) -> None:
    width, _ = viewport
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    page.goto(url)
    page.get_by_label("Password", exact=True).wait_for(state="visible")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role(
        "heading", name="Your books at a glance", exact=True
    ).wait_for(state="visible")
    open_sidebar_for_narrow_view(page, width)
    assets_route = page.get_by_role("radio", name="Assets", exact=True)
    assets_route.wait_for(state="visible", timeout=10000)
    if width <= 600:
        assets_route.evaluate("element => element.click()")
    else:
        page.get_by_text("Assets", exact=True).first.click()

    page.get_by_role("heading", name="Assets", exact=True).wait_for(state="visible")
    page.get_by_text("Add asset", exact=True).first.click()
    require_input(page, "Asset name")
    require_input(page, "Useful life (quarters)")
    require_input(page, "Cost basis")
    page.get_by_text("Depreciation expense account", exact=True).first.wait_for(state="visible")
    page.get_by_text("Accumulated depreciation account", exact=True).first.wait_for(state="visible")
    page.get_by_role("button", name="Post due depreciation", exact=True).wait_for(state="visible")
    page.get_by_text("Post depreciation through", exact=True).first.wait_for(state="visible")
    page.get_by_role(
        "button", name="Calculate quarterly schedule", exact=True
    ).click()
    page.get_by_text("Quarterly depreciation schedule", exact=False).first.wait_for(
        state="visible", timeout=10000
    )
    page.locator('[data-testid="stDataFrameResizable"]').last.wait_for(
        state="visible", timeout=10000
    )
    assert_no_page_overflow(page)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        failures = run_smoke_check(
            args.screenshots_dir,
            args.port,
            page_check=check_assets_viewport,
        )
    except SmokeCheckFailure as error:
        print(f"Assets smoke check failed: {error}")
        return 1
    if failures:
        print("Assets viewport smoke check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "Assets viewport smoke check passed at "
        + ", ".join(f"{width}x{height}" for width, height in VIEWPORTS)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
