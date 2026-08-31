"""Nightly auto-PO: watermark diff, preferred-vendor filtering, net_need
ceiling, BC draft creation, and the SO-allocation record."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import AutoPoSnapshot, POAgentLog
from app.services.auto_po_service import (
    AutoPoService,
    SKIP_MANUFACTURED,
    SKIP_UNASSIGNED,
    SKIP_EXPEDITE,
    SKIP_COVERED,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    AutoPoSnapshot.__table__.create(engine)
    POAgentLog.__table__.create(engine)
    return sessionmaker(bind=engine)()


# ── fake BC surface ────────────────────────────────────────────────────

class FakeBC:
    def __init__(self, sales_orders):
        self._sos = sales_orders
        self.created = []
        self.lines = []
        self._counter = 0

    def get_open_sales_orders_with_lines(self):
        return self._sos

    def create_purchase_order(self, body):
        self._counter += 1
        po = {"id": f"guid-{self._counter}", "number": f"PO-TEST-{self._counter}",
              "status": "Draft", **body}
        self.created.append(po)
        return po

    def add_purchase_order_line(self, po_id, body):
        self.lines.append((po_id, body))
        return {"id": f"line-{len(self.lines)}"}


def _so(number, lines, rdd="2026-09-15"):
    return {"number": number, "requestedDeliveryDate": rdd,
            "salesOrderLines": [
                {"lineType": "Item", "sequence": i * 1000,
                 "lineObjectNumber": itm, "quantity": q, "shippedQuantity": s,
                 "description": f"desc {itm}"}
                for i, (itm, q, s) in enumerate(lines, start=1)
            ]}


def _wire(monkeypatch, svc, *, requirements, replen=None, vendor_map=None):
    monkeypatch.setattr(
        "app.services.auto_po_service.purchasing_demand_service.compute_requirements",
        lambda db, **kw: requirements,
    )
    monkeypatch.setattr(
        "app.services.auto_po_service.bc_production_service.get_replenishment_map",
        lambda: replen or {},
    )
    monkeypatch.setattr(
        "app.services.auto_po_service.vendor_map_service.load_map",
        lambda db: vendor_map or {},
    )
    monkeypatch.setattr(
        "app.services.auto_po_service.vendor_map_service.refresh",
        lambda db: None,
    )


def _req(items):
    return {"items": items, "summary": {}, "vendors": []}


# ── tests ──────────────────────────────────────────────────────────────

def test_new_line_drafts_a_po_for_preferred_vendor(monkeypatch):
    db = _db()
    bc = FakeBC([_so("SO-1001", [("PL10-16203-00", 4, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([{"item_no": "PL10-16203-00", "net_need": 4,
                              "description": "Weatherstrip 16", "unit_cost": 300,
                              "last_purchase_cost": 311.0, "unit_of_measure": "BU"}]),
          vendor_map={"PL10-16203-00": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"}})

    result = svc.run(db, dry_run=False)

    assert result["drafted_po_count"] == 1
    assert len(bc.created) == 1
    assert bc.created[0]["vendorNumber"] == "UPW"
    log = db.query(POAgentLog).one()
    assert log.is_auto is True
    assert log.so_allocations == {"SO-1001": [{"item_no": "PL10-16203-00", "qty": 4.0}]}
    # comment line naming the SO went onto the PO
    assert any("SO-1001" in body.get("description", "") for _id, body in bc.lines
               if body.get("lineType") == "Comment")
    # watermark advanced so a second run does nothing
    snap = db.query(AutoPoSnapshot).one()
    assert snap.covered_qty == 4.0


def test_second_run_no_new_demand_drafts_nothing(monkeypatch):
    db = _db()
    bc = FakeBC([_so("SO-1001", [("PL10-16203-00", 4, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    reqs = _req([{"item_no": "PL10-16203-00", "net_need": 4, "description": "WS",
                  "unit_cost": 300, "last_purchase_cost": 311.0}])
    _wire(monkeypatch, svc, requirements=reqs,
          vendor_map={"PL10-16203-00": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"}})

    svc.run(db, dry_run=False)
    bc.created.clear()
    result = svc.run(db, dry_run=False)

    assert result["drafted_po_count"] == 0
    assert bc.created == []


def test_quantity_increase_drafts_only_the_delta(monkeypatch):
    db = _db()
    svc = AutoPoService()
    db.add(AutoPoSnapshot(so_number="SO-1", sequence=1000, item_no="X1",
                          outstanding_seen=4, covered_qty=4))
    db.commit()
    bc = FakeBC([_so("SO-1", [("X1", 10, 0)])])   # grew 4 -> 10
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    _wire(monkeypatch, svc,
          requirements=_req([{"item_no": "X1", "net_need": 10, "description": "x",
                              "unit_cost": 5, "last_purchase_cost": 5}]),
          vendor_map={"X1": {"vendor_no": "LYNX", "vendor_name": "LYNX"}})

    result = svc.run(db, dry_run=False)

    line = result["drafts"][0]["lines"][0]
    assert line["quantity"] == 6          # 10 - 4 already covered
    assert db.query(AutoPoSnapshot).one().covered_qty == 10.0


def test_net_need_ceiling_caps_the_draft(monkeypatch):
    """New SO demand is 8 but stock already covers 5, so net_need is 3 —
    draft 3, not 8."""
    db = _db()
    bc = FakeBC([_so("SO-9", [("ITM", 8, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([{"item_no": "ITM", "net_need": 3, "description": "i",
                              "unit_cost": 2, "last_purchase_cost": 2}]),
          vendor_map={"ITM": {"vendor_no": "ELT", "vendor_name": "ELTON"}})

    result = svc.run(db, dry_run=False)
    assert result["drafts"][0]["lines"][0]["quantity"] == 3


def test_manufactured_item_is_skipped(monkeypatch):
    db = _db()
    bc = FakeBC([_so("SO-2", [("PN45-PANEL", 3, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([{"item_no": "PN45-PANEL", "net_need": 3, "description": "panel",
                              "unit_cost": 100, "last_purchase_cost": 100}]),
          replen={"PN45-PANEL": "Prod. Order"},
          vendor_map={"PN45-PANEL": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"}})

    result = svc.run(db, dry_run=False)
    assert bc.created == []
    assert result["skipped_counts"].get(SKIP_MANUFACTURED) == 1


def test_unassigned_and_expedite_vendors_are_skipped(monkeypatch):
    db = _db()
    bc = FakeBC([_so("SO-3", [("A", 1, 0), ("B", 1, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([
              {"item_no": "A", "net_need": 1, "description": "a", "unit_cost": 1, "last_purchase_cost": 1},
              {"item_no": "B", "net_need": 1, "description": "b", "unit_cost": 1, "last_purchase_cost": 1},
          ]),
          vendor_map={"B": {"vendor_no": "DEK", "vendor_name": "DEK CANADA"}})

    result = svc.run(db, dry_run=False)
    assert bc.created == []
    assert result["skipped_counts"].get(SKIP_UNASSIGNED) == 1
    assert result["skipped_counts"].get(SKIP_EXPEDITE) == 1


def test_dry_run_touches_nothing(monkeypatch):
    db = _db()
    bc = FakeBC([_so("SO-4", [("ITM", 2, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([{"item_no": "ITM", "net_need": 2, "description": "i",
                              "unit_cost": 9, "last_purchase_cost": 9}]),
          vendor_map={"ITM": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"}})

    result = svc.run(db, dry_run=True)

    assert result["dry_run"] is True
    assert len(result["drafts"]) == 1 and result["drafts"][0]["dry_run"] is True
    assert bc.created == []
    assert db.query(AutoPoSnapshot).count() == 0
    assert db.query(POAgentLog).count() == 0


def test_two_items_same_vendor_go_on_one_po(monkeypatch):
    db = _db()
    bc = FakeBC([_so("SO-5", [("P1", 2, 0), ("P2", 3, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([
              {"item_no": "P1", "net_need": 2, "description": "p1", "unit_cost": 1, "last_purchase_cost": 1},
              {"item_no": "P2", "net_need": 3, "description": "p2", "unit_cost": 1, "last_purchase_cost": 1},
          ]),
          vendor_map={
              "P1": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"},
              "P2": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"},
          })

    result = svc.run(db, dry_run=False)
    assert result["drafted_po_count"] == 1
    assert len(result["drafts"][0]["lines"]) == 2


def test_seed_snapshot_makes_first_run_quiet(monkeypatch):
    db = _db()
    bc = FakeBC([_so("SO-8", [("ITM", 7, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([{"item_no": "ITM", "net_need": 7, "description": "i",
                              "unit_cost": 3, "last_purchase_cost": 3}]),
          vendor_map={"ITM": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"}})

    seed = svc.seed_snapshot(db)
    assert seed["lines_seeded"] == 1
    result = svc.run(db, dry_run=False)
    assert bc.created == []
    assert result["drafted_po_count"] == 0
    # a later increase still gets drafted
    bc._sos = [_so("SO-8", [("ITM", 10, 0)])]
    result2 = svc.run(db, dry_run=False)
    assert result2["drafts"][0]["lines"][0]["quantity"] == 3


def test_only_vendors_restricts_and_leaves_the_rest(monkeypatch):
    db = _db()
    bc = FakeBC([_so("SO-20", [("A", 2, 0), ("B", 3, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([
              {"item_no": "A", "net_need": 2, "description": "a", "unit_cost": 1, "last_purchase_cost": 1},
              {"item_no": "B", "net_need": 3, "description": "b", "unit_cost": 1, "last_purchase_cost": 1},
          ]),
          vendor_map={
              "A": {"vendor_no": "ELT", "vendor_name": "ELTON"},
              "B": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"},
          })

    result = svc.run(db, dry_run=False, only_vendors={"ELT"})
    assert result["drafted_po_count"] == 1
    assert bc.created[0]["vendorNumber"] == "ELT"
    assert result["skipped_counts"].get("vendor_not_in_scope") == 1
    # the UPW line's watermark was NOT advanced — a later full run still drafts it
    upw_line = db.query(AutoPoSnapshot).filter_by(item_no="B").one()
    assert upw_line.covered_qty == 0.0


def test_prior_draft_allocation_prevents_redraft_after_snapshot_loss(monkeypatch):
    db = _db()
    # a PO we drafted yesterday, snapshot since wiped
    db.add(POAgentLog(vendor_name="UPWARDOR", vendor_id="UPW", status="submitted",
                      is_auto=True, line_items=[], currency="CAD",
                      so_allocations={"SO-7": [{"item_no": "ITM", "qty": 5.0}]}))
    db.commit()
    bc = FakeBC([_so("SO-7", [("ITM", 5, 0)])])
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    svc = AutoPoService()
    _wire(monkeypatch, svc,
          requirements=_req([{"item_no": "ITM", "net_need": 5, "description": "i",
                              "unit_cost": 3, "last_purchase_cost": 3}]),
          vendor_map={"ITM": {"vendor_no": "UPW", "vendor_name": "UPWARDOR"}})

    result = svc.run(db, dry_run=False)
    assert bc.created == []
    assert result["skipped_counts"].get(SKIP_COVERED) == 1
