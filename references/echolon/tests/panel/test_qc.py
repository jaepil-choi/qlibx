from __future__ import annotations

import datetime as dt

import pandas as pd

from echolon.panel.qc import run_panel_qc


def test_qc_fails_on_zero_price_and_bad_curve_order():
    bars = {
        "al": pd.DataFrame(
            [
                {
                    "open": 19000.0,
                    "high": 19100.0,
                    "low": 18900.0,
                    "close": 19000.0,
                    "settle": 19000.0,
                    "volume": 100,
                    "open_interest": 1000,
                    "contract": "al2402",
                },
                {
                    "open": 0.0,
                    "high": 19100.0,
                    "low": 18900.0,
                    "close": 19020.0,
                    "settle": 19020.0,
                    "volume": 100,
                    "open_interest": 1000,
                    "contract": "al2402",
                },
            ],
            index=[dt.date(2024, 1, 2), dt.date(2024, 1, 3)],
        )
    }
    curves = {
        "al": pd.DataFrame(
            [
                {
                    "near_contract": "al2403",
                    "near_settle": 19010.0,
                    "far_contract": "al2402",
                    "far_settle": 19080.0,
                    "days_between": 30,
                }
            ],
            index=[dt.date(2024, 1, 3)],
        )
    }

    report = run_panel_qc(snapshot="synthetic", bars=bars, curves=curves)

    assert report.schema == "qc/v1"
    assert report.status == "FAIL"
    severities = {check.severity for check in report.checks}
    assert "ERROR" in severities
    assert {check.check_id for check in report.checks} >= {
        "price_positive",
        "curve_contract_order",
    }


def test_qc_v3_errors_gate_coverage_duplicates_negative_receipts_and_units():
    calendar = [dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
    inventory = {
        "al": pd.DataFrame(
            {"receipts": [10.0, -1.0], "unit": ["ton", ""]},
            index=[calendar[0], calendar[0]],
        )
    }
    positioning = {
        "al": pd.DataFrame(
            {"long_oi_top20": [6.0], "short_oi_top20": [4.0], "net_share": [0.2]},
            index=[calendar[0]],
        )
    }

    report = run_panel_qc(
        snapshot="v3",
        bars={},
        curves={},
        inventory=inventory,
        positioning=positioning,
        trading_calendars={"al": calendar},
    )

    assert report.status == "FAIL"
    assert {check.check_id for check in report.checks} >= {
        "inventory_coverage",
        "inventory_duplicate_date",
        "inventory_receipts_nonnegative",
        "inventory_unit_value_present",
        "positioning_coverage",
    }
    assert {check.severity for check in report.checks} == {"ERROR"}


def test_qc_v3_requires_inventory_unit_column():
    date = dt.date(2024, 1, 2)

    report = run_panel_qc(
        snapshot="v3",
        bars={},
        curves={},
        inventory={"al": pd.DataFrame({"receipts": [1.0]}, index=[date])},
        positioning={},
        trading_calendars={"al": [date]},
    )

    assert report.status == "FAIL"
    assert [check.check_id for check in report.checks] == ["inventory_unit_column_present"]


def test_qc_v3_item_waiver_needs_owner_visible_reason_and_approver():
    date = dt.date(2024, 1, 2)
    kwargs = dict(
        snapshot="v3",
        bars={},
        curves={},
        inventory={"al": pd.DataFrame({"receipts": [-1.0], "unit": ["ton"]}, index=[date])},
        positioning={},
        trading_calendars={"al": [date]},
    )

    unapproved = run_panel_qc(
        **kwargs,
        waivers={("al", date, "inventory_receipts_nonnegative"): "known correction"},
    )
    approved = run_panel_qc(
        **kwargs,
        waivers={("al", date, "inventory_receipts_nonnegative"): {"reason": "exchange correction", "approved_by": "owner"}},
    )

    assert unapproved.status == "FAIL"
    assert unapproved.checks[0].waived is False
    assert approved.status == "PASS_WITH_WARNINGS"
    assert approved.checks[0].waived is True
    assert approved.checks[0].waiver_reason == "exchange correction"
    assert approved.checks[0].waiver_approved_by == "owner"


def test_qc_v3_coverage_uses_first_availability_and_error_threshold():
    calendar = [dt.date(2024, 1, 1) + dt.timedelta(days=offset) for offset in range(201)]
    positioning = pd.DataFrame(
        {"long_oi_top20": 1.0, "short_oi_top20": 1.0, "net_share": 0.0},
        index=calendar[1:200],
    )

    report = run_panel_qc(
        snapshot="v3",
        bars={},
        curves={},
        inventory={},
        positioning={"al": positioning},
        trading_calendars={"al": calendar},
    )

    assert report.status == "PASS"
    assert report.checks == []


def test_qc_warns_on_zero_volume_and_settle_close_divergence():
    bars = {
        "al": pd.DataFrame(
            [
                {
                    "open": 19000.0,
                    "high": 19100.0,
                    "low": 18900.0,
                    "close": 19000.0,
                    "settle": 19000.0,
                    "volume": 100,
                    "open_interest": 1000,
                    "contract": "al2402",
                },
                {
                    "open": 19010.0,
                    "high": 19110.0,
                    "low": 18910.0,
                    "close": 19020.0,
                    "settle": 19600.0,
                    "volume": 0,
                    "open_interest": 1000,
                    "contract": "al2402",
                },
            ],
            index=[dt.date(2024, 1, 2), dt.date(2024, 1, 3)],
        )
    }

    report = run_panel_qc(snapshot="synthetic", bars=bars, curves={})

    assert report.status == "PASS_WITH_WARNINGS"
    assert {check.severity for check in report.checks} == {"WARN"}
    assert {check.check_id for check in report.checks} >= {
        "volume_nonzero",
        "settle_close_divergence",
    }


def test_qc_fails_unadjusted_roll_gap_above_hard_return_threshold():
    bars = {
        "fu": pd.DataFrame(
            [
                {
                    "open": 2300.0,
                    "high": 2310.0,
                    "low": 2290.0,
                    "close": 2300.0,
                    "settle": 2300.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2401",
                },
                {
                    "open": 2600.0,
                    "high": 2610.0,
                    "low": 2590.0,
                    "close": 2600.0,
                    "settle": 2600.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2405",
                },
                {
                    "open": 2610.0,
                    "high": 2620.0,
                    "low": 2360.0,
                    "close": 2360.0,
                    "settle": 2600.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2405",
                },
            ],
            index=[dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4)],
        )
    }

    report = run_panel_qc(snapshot="synthetic", bars=bars, curves={})

    assert report.status == "FAIL"
    assert any(
        check.check_id == "daily_return_threshold"
        and check.severity == "ERROR"
        and check.date == dt.date(2024, 1, 3)
        for check in report.checks
    )


def test_qc_allows_adjusted_roll_series_and_still_flags_real_outliers():
    bars = {
        "fu": pd.DataFrame(
            [
                {
                    "open": 2530.0,
                    "high": 2541.0,
                    "low": 2519.0,
                    "close": 2530.0,
                    "settle": 2530.0,
                    "open_raw": 2300.0,
                    "high_raw": 2310.0,
                    "low_raw": 2290.0,
                    "close_raw": 2300.0,
                    "settle_raw": 2300.0,
                    "adj_factor": 1.1,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2401",
                },
                {
                    "open": 2540.0,
                    "high": 2550.0,
                    "low": 2530.0,
                    "close": 2540.0,
                    "settle": 2540.0,
                    "open_raw": 2600.0,
                    "high_raw": 2610.0,
                    "low_raw": 2590.0,
                    "close_raw": 2600.0,
                    "settle_raw": 2600.0,
                    "adj_factor": 1.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2405",
                },
                {
                    "open": 2550.0,
                    "high": 2560.0,
                    "low": 2360.0,
                    "close": 2360.0,
                    "settle": 2540.0,
                    "open_raw": 2610.0,
                    "high_raw": 2620.0,
                    "low_raw": 2360.0,
                    "close_raw": 2360.0,
                    "settle_raw": 2600.0,
                    "adj_factor": 1.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2405",
                },
            ],
            index=[dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4)],
        )
    }

    report = run_panel_qc(snapshot="synthetic", bars=bars, curves={})

    assert report.status == "PASS_WITH_WARNINGS"
    assert {check.severity for check in report.checks} == {"WARN"}
    assert {check.check_id for check in report.checks} == {
        "settle_close_divergence",
        "daily_return_threshold",
    }
    assert not any(
        check.check_id == "daily_return_threshold" and check.date == dt.date(2024, 1, 3)
        for check in report.checks
    )


def test_qc_specific_waiver_keeps_hard_error_visible_but_nonblocking():
    date = dt.date(2024, 1, 3)
    bars = {
        "ni": pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 100.0,
                    "low": 100.0,
                    "close": 100.0,
                    "settle": 100.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "ni2401",
                },
                {
                    "open": 130.0,
                    "high": 130.0,
                    "low": 130.0,
                    "close": 130.0,
                    "settle": 130.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "ni2401",
                },
            ],
            index=[dt.date(2024, 1, 2), date],
        )
    }

    report = run_panel_qc(
        snapshot="synthetic",
        bars=bars,
        curves={},
        waivers={
            ("ni", date, "daily_return_threshold"): {
                "reason": "exchange stress day retained",
                "approved_by": "owner",
            }
        },
    )

    assert report.status == "PASS_WITH_WARNINGS"
    hard = [check for check in report.checks if check.severity == "ERROR"]
    assert len(hard) == 1
    assert hard[0].waived is True
    assert hard[0].waiver_reason == "exchange stress day retained"
    assert hard[0].waiver_approved_by == "owner"


def test_qc_waiver_without_approver_remains_blocking():
    date = dt.date(2024, 1, 3)
    bars = {
        "ni": pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 100.0,
                    "low": 100.0,
                    "close": 100.0,
                    "settle": 100.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "ni2401",
                },
                {
                    "open": 130.0,
                    "high": 130.0,
                    "low": 130.0,
                    "close": 130.0,
                    "settle": 130.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "ni2401",
                },
            ],
            index=[dt.date(2024, 1, 2), date],
        )
    }

    report = run_panel_qc(
        snapshot="synthetic",
        bars=bars,
        curves={},
        waivers={("ni", date, "daily_return_threshold"): "reason without approver"},
    )

    assert report.status == "FAIL"
    hard = [check for check in report.checks if check.severity == "ERROR"]
    assert len(hard) == 1
    assert hard[0].waived is False
    assert hard[0].waiver_reason == "reason without approver"
    assert hard[0].waiver_approved_by is None
