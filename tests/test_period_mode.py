from scripts.server import fiscal_period_rows


def test_mtd_contains_only_selected_month():
    rows = fiscal_period_rows("Sep-2026", "MTD")
    assert [row["reporting_month"] for row in rows] == ["September,26"]
    assert rows[0]["suffix"] == "sep_26"


def test_ytd_contains_fiscal_year_to_selected_month():
    rows = fiscal_period_rows("Sep-2026", "YTD")
    assert [row["reporting_month"] for row in rows] == [
        "July,26", "August,26", "September,26"
    ]


def test_ytd_rolls_across_calendar_year():
    rows = fiscal_period_rows("Feb-2027", "YTD")
    assert rows[0]["reporting_month"] == "July,26"
    assert rows[-1]["reporting_month"] == "February,27"
    assert len(rows) == 8
