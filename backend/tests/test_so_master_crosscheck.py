"""Cross-check between so_coverage_service (our raw-material purchasing
netting) and BC's native SalesOrderMaster per-line production status.
See so_master_crosscheck_service module docstring for what a disagreement
means in each direction.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.so_master_crosscheck_service import (
    SOMasterCrossCheckService,
    BC_UNSCHEDULED_STATUS,
)


def _line(so_no, part_no, status, prodn_order_no=""):
    return {
        "Sales_Order_No": so_no,
        "Part_No": part_no,
        "Status": status,
        "Prodn_Order_No": prodn_order_no,
    }


def test_bc_ready_true_when_no_unscheduled_lines():
    svc = SOMasterCrossCheckService()
    lines = [
        _line("SO-1", "PN65-001", "From Stock"),
        _line("SO-1", "SP12-001", "Finished", "PROD-001"),
    ]
    signal = svc._bc_signal(lines)
    assert signal["bc_ready"] is True
    assert signal["unscheduled_count"] == 0


def test_bc_ready_false_when_any_line_unscheduled():
    svc = SOMasterCrossCheckService()
    lines = [
        _line("SO-1", "PN65-001", "From Stock"),
        _line("SO-1", "GK15-001", BC_UNSCHEDULED_STATUS, "PROD-002"),
    ]
    signal = svc._bc_signal(lines)
    assert signal["bc_ready"] is False
    assert signal["unscheduled_count"] == 1
    assert signal["unscheduled_parts"] == ["GK15-001"]


def test_agrees_when_our_covered_matches_bc_ready(monkeypatch):
    svc = SOMasterCrossCheckService()
    coverage = {
        "generated_at": "2026-08-26T00:00:00",
        "orders": [
            {"so_number": "SO-1", "customer": "Acme", "status": "covered", "urgency": "scheduled"},
        ],
    }
    monkeypatch.setattr(
        "app.services.so_master_crosscheck_service.so_coverage_service.build",
        lambda db, **kw: coverage,
    )
    monkeypatch.setattr(
        "app.services.so_master_crosscheck_service.bc_production_service.get_sales_order_master",
        lambda: [_line("SO-1", "PN65-001", "From Stock")],
    )

    result = svc.build(db=None)
    assert result["disagree_count"] == 0
    assert result["agree_count"] == 1
    assert result["rows"][0]["agrees"] is True


def test_disagrees_when_our_covered_but_bc_has_unscheduled_line(monkeypatch):
    """Purchasing looks done, but BC shows a component still mid-production —
    the order can't actually ship yet."""
    svc = SOMasterCrossCheckService()
    coverage = {
        "generated_at": "2026-08-26T00:00:00",
        "orders": [
            {"so_number": "SO-1", "customer": "Acme", "status": "covered", "urgency": "scheduled"},
        ],
    }
    monkeypatch.setattr(
        "app.services.so_master_crosscheck_service.so_coverage_service.build",
        lambda db, **kw: coverage,
    )
    monkeypatch.setattr(
        "app.services.so_master_crosscheck_service.bc_production_service.get_sales_order_master",
        lambda: [_line("SO-1", "GK15-001", BC_UNSCHEDULED_STATUS, "PROD-002")],
    )

    result = svc.build(db=None)
    assert result["disagree_count"] == 1
    assert result["disagreements"][0]["so_number"] == "SO-1"
    assert result["disagreements"][0]["bc_ready"] is False
    assert result["disagreements"][0]["our_status"] == "covered"


def test_disagrees_when_our_gap_but_bc_shows_all_lines_clear(monkeypatch):
    """Our raw-material netting flags a gap, but BC shows everything already
    From Stock/Finished — a lead that our netting has a false positive."""
    svc = SOMasterCrossCheckService()
    coverage = {
        "generated_at": "2026-08-26T00:00:00",
        "orders": [
            {"so_number": "SO-2", "customer": "Acme", "status": "gap", "urgency": "urgent"},
        ],
    }
    monkeypatch.setattr(
        "app.services.so_master_crosscheck_service.so_coverage_service.build",
        lambda db, **kw: coverage,
    )
    monkeypatch.setattr(
        "app.services.so_master_crosscheck_service.bc_production_service.get_sales_order_master",
        lambda: [_line("SO-2", "PN65-001", "From Stock")],
    )

    result = svc.build(db=None)
    assert result["disagree_count"] == 1
    assert result["disagreements"][0]["our_status"] == "gap"
    assert result["disagreements"][0]["bc_ready"] is True


def test_so_missing_from_bc_master_is_excluded_not_counted_as_disagreement(monkeypatch):
    svc = SOMasterCrossCheckService()
    coverage = {
        "generated_at": "2026-08-26T00:00:00",
        "orders": [
            {"so_number": "SO-3", "customer": "Acme", "status": "covered", "urgency": "scheduled"},
        ],
    }
    monkeypatch.setattr(
        "app.services.so_master_crosscheck_service.so_coverage_service.build",
        lambda db, **kw: coverage,
    )
    monkeypatch.setattr(
        "app.services.so_master_crosscheck_service.bc_production_service.get_sales_order_master",
        lambda: [],  # SO-3 never appears
    )

    result = svc.build(db=None)
    assert result["matched_in_bc_master"] == 0
    assert result["unmatched_in_bc_master"] == 1
    assert result["disagree_count"] == 0
    assert result["rows"] == []
