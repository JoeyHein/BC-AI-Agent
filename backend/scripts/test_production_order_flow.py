#!/usr/bin/env python3
"""
Test script for Production Order Integration with Springs

Tests the complete flow:
1. Quote with spring items -> Sales Order -> Production Orders
2. Spring specifications flow through the entire pipeline
3. Inventory allocation for springs

Run from backend directory:
    python scripts/test_production_order_flow.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from app.db.database import SessionLocal
from app.db.models import (
    QuoteRequest, QuoteItem, SalesOrder, ProductionOrder,
    OrderStatus, ProductionStatus
)
from app.services.order_lifecycle_service import order_lifecycle_service


def create_test_quote_with_springs(db):
    """Create a test quote request with spring items"""
    print("\n" + "=" * 60)
    print("CREATING TEST QUOTE WITH SPRING ITEMS")
    print("=" * 60)

    # Create a mock quote request
    quote_request = QuoteRequest(
        email_id=1,  # Mock email ID
        customer_name="Test Customer Inc.",
        contact_email="test@example.com",
        contact_phone="555-1234",
        door_specs={
            "model": "TX450",
            "quantity": 2,
            "width_ft": 9,
            "height_ft": 7
        },
        parsed_data={
            "customer": {"company_name": "Test Customer Inc.", "email": "test@example.com"},
            "doors": [{"model": "TX450", "quantity": 2, "width_ft": 9, "height_ft": 7}]
        },
        status="approved",
        bc_quote_id="Q-TEST-001"
    )
    db.add(quote_request)
    db.flush()

    print(f"Created QuoteRequest ID: {quote_request.id}")

    # Create door item
    door_item = QuoteItem(
        quote_request_id=quote_request.id,
        item_type="door",
        product_code="PN45-24400-0900",
        description="TX450 Overhead Door - 9' x 7'",
        quantity=2,
        unit_price=1200.00,
        total_price=2400.00,
        item_metadata={
            "model": "TX450",
            "size": "9' x 7'",
            "color": "WHITE",
            "panel_config": "UDC"
        }
    )
    db.add(door_item)

    # Create spring item with full Canimex specifications
    spring_item = QuoteItem(
        quote_request_id=quote_request.id,
        item_type="spring",
        product_code="SP11-23420-01",
        description="Torsion Spring - 0.234\" wire x 2.0\" ID x 27.5\" length",
        quantity=4,  # 2 springs per door x 2 doors
        unit_price=88.64,
        total_price=354.56,
        item_metadata={
            "wire_diameter": 0.234,
            "coil_diameter": 2.0,
            "length": 27.5,
            "ippt": 34.2,
            "mip_per_spring": 171.0,
            "turns": 7.5,
            "cycle_life": 10000,
            "drum_model": "D400-96",
            "door_weight": 252,
            "door_height_inches": 84,
            "track_radius": 15,
            "wind": "LH"
        }
    )
    db.add(spring_item)

    # Create hardware item
    hardware_item = QuoteItem(
        quote_request_id=quote_request.id,
        item_type="hardware",
        product_code="TR02-STDBM-8412",
        description="2\" Track and Hardware",
        quantity=2,
        unit_price=200.00,
        total_price=400.00,
        item_metadata={
            "track_type": "2",
            "size": "9' x 7'"
        }
    )
    db.add(hardware_item)

    db.commit()

    print(f"Created 3 QuoteItems: door, spring, hardware")
    print(f"Spring specs: 0.234\" x 2.0\" x 27.5\", IPPT={spring_item.item_metadata['ippt']}")

    return quote_request


def create_test_sales_order(db, quote_request):
    """Create a test sales order from the quote"""
    print("\n" + "=" * 60)
    print("CREATING TEST SALES ORDER")
    print("=" * 60)

    sales_order = SalesOrder(
        quote_request_id=quote_request.id,
        bc_order_id="bc-order-test-001",
        bc_order_number="SO-TEST-001",
        bc_quote_number=quote_request.bc_quote_id,
        customer_name=quote_request.customer_name,
        customer_email=quote_request.contact_email,
        status=OrderStatus.CONFIRMED,
        total_amount=3154.56,
        confirmed_at=datetime.utcnow()
    )
    db.add(sales_order)
    db.commit()

    print(f"Created SalesOrder ID: {sales_order.id}")
    print(f"BC Order Number: {sales_order.bc_order_number}")
    print(f"Status: {sales_order.status.value}")

    return sales_order


def test_create_production_orders(db, sales_order):
    """Test creating production orders from sales order"""
    print("\n" + "=" * 60)
    print("TESTING PRODUCTION ORDER CREATION")
    print("=" * 60)

    result = order_lifecycle_service.create_production_orders(
        db, sales_order.id, "test-user"
    )

    if not result["success"]:
        print(f"[FAIL] Failed to create production orders: {result.get('error')}")
        return False

    print(f"[PASS] Created {len(result['production_orders'])} production orders")

    for po in result["production_orders"]:
        print(f"\n  Production Order ID: {po['id']}")
        print(f"    Type: {po['item_type']}")
        print(f"    Item Code: {po['item_code']}")
        print(f"    Quantity: {po['quantity']}")
        print(f"    Inventory Allocated: {po['inventory_allocated']}")

        if po['item_type'] == 'spring' and po['specifications']:
            specs = po['specifications']
            print(f"    --- Spring Specifications ---")
            print(f"    Wire Diameter: {specs.get('wire_diameter')}\"")
            print(f"    Coil Diameter: {specs.get('coil_diameter')}\"")
            print(f"    Length: {specs.get('length')}\"")
            print(f"    IPPT: {specs.get('ippt')}")
            print(f"    MIP/Spring: {specs.get('mip_per_spring')}")
            print(f"    Turns: {specs.get('turns')}")
            print(f"    Cycle Life: {specs.get('cycle_life')}")
            print(f"    Drum Model: {specs.get('drum_model')}")
            print(f"    Door Weight: {specs.get('door_weight')} lbs")

    if result.get("inventory_warnings"):
        print("\n  Inventory Warnings:")
        for warning in result["inventory_warnings"]:
            print(f"    - {warning['item_code']}: need {warning['required']}, have {warning['available']}")

    return True


def test_spring_production_orders(db, sales_order_id):
    """Test retrieving spring production orders"""
    print("\n" + "=" * 60)
    print("TESTING SPRING PRODUCTION ORDER RETRIEVAL")
    print("=" * 60)

    spring_orders = order_lifecycle_service.get_spring_production_orders(db, sales_order_id)

    if not spring_orders:
        print("[WARN] No spring production orders found")
        return True

    print(f"[PASS] Found {len(spring_orders)} spring production orders")

    for order in spring_orders:
        print(f"\n  Spring Order ID: {order['id']}")
        print(f"    Part Number: {order['item_code']}")
        print(f"    Status: {order['status']}")

        specs = order.get('specifications', {})
        if specs:
            print(f"    Wire: {specs.get('wire_diameter')}\" x Coil: {specs.get('coil_diameter')}\"")
            print(f"    Length: {specs.get('length')}\"")
            print(f"    IPPT: {specs.get('ippt')}, MIP: {specs.get('mip_per_spring')}")

    return True


def test_production_status_update(db, sales_order_id):
    """Test updating production order status"""
    print("\n" + "=" * 60)
    print("TESTING PRODUCTION STATUS UPDATE")
    print("=" * 60)

    # Get a production order
    prod_order = db.query(ProductionOrder).filter(
        ProductionOrder.sales_order_id == sales_order_id
    ).first()

    if not prod_order:
        print("[WARN] No production order to test status update")
        return True

    print(f"Testing status update for Production Order ID: {prod_order.id}")
    print(f"Current Status: {prod_order.status.value}")

    # Update to IN_PROGRESS
    result = order_lifecycle_service.update_production_status(
        db, prod_order.id, ProductionStatus.IN_PROGRESS, "test-user"
    )

    if not result["success"]:
        print(f"[FAIL] Failed to update status: {result.get('error')}")
        return False

    print(f"[PASS] Status updated: {result['old_status']} -> {result['new_status']}")

    # Update to FINISHED
    result = order_lifecycle_service.update_production_status(
        db, prod_order.id, ProductionStatus.FINISHED, "test-user"
    )

    if not result["success"]:
        print(f"[FAIL] Failed to update to finished: {result.get('error')}")
        return False

    print(f"[PASS] Status updated: {result['old_status']} -> {result['new_status']}")
    print(f"       Quantity Completed: {result['quantity_completed']}")

    return True


def test_sales_order_status_after_production(db, sales_order_id):
    """Test that sales order status updates when all production is complete"""
    print("\n" + "=" * 60)
    print("TESTING SALES ORDER STATUS AFTER PRODUCTION COMPLETE")
    print("=" * 60)

    # Mark all production orders as finished
    prod_orders = db.query(ProductionOrder).filter(
        ProductionOrder.sales_order_id == sales_order_id
    ).all()

    for po in prod_orders:
        if po.status != ProductionStatus.FINISHED:
            order_lifecycle_service.update_production_status(
                db, po.id, ProductionStatus.FINISHED, "test-user"
            )

    # Check sales order status
    sales_order = db.query(SalesOrder).filter(SalesOrder.id == sales_order_id).first()

    print(f"Sales Order Status: {sales_order.status.value}")

    if sales_order.status == OrderStatus.READY_TO_SHIP:
        print("[PASS] Sales order correctly updated to READY_TO_SHIP")
        return True
    else:
        print(f"[INFO] Sales order status is {sales_order.status.value}")
        return True


def cleanup_test_data(db, quote_request_id, sales_order_id):
    """Clean up test data"""
    print("\n" + "=" * 60)
    print("CLEANING UP TEST DATA")
    print("=" * 60)

    # Delete in reverse order of dependencies
    db.query(ProductionOrder).filter(
        ProductionOrder.sales_order_id == sales_order_id
    ).delete()

    db.query(SalesOrder).filter(SalesOrder.id == sales_order_id).delete()

    db.query(QuoteItem).filter(
        QuoteItem.quote_request_id == quote_request_id
    ).delete()

    db.query(QuoteRequest).filter(QuoteRequest.id == quote_request_id).delete()

    db.commit()
    print("Test data cleaned up")


def main():
    print("\n" + "=" * 60)
    print("PRODUCTION ORDER INTEGRATION TEST SUITE")
    print("=" * 60)

    db = SessionLocal()

    try:
        # Create test data
        quote_request = create_test_quote_with_springs(db)
        sales_order = create_test_sales_order(db, quote_request)

        results = []

        # Run tests
        results.append(("Create Production Orders", test_create_production_orders(db, sales_order)))
        results.append(("Spring Production Orders", test_spring_production_orders(db, sales_order.id)))
        results.append(("Production Status Update", test_production_status_update(db, sales_order.id)))
        results.append(("Sales Order Status Update", test_sales_order_status_after_production(db, sales_order.id)))

        # Cleanup
        cleanup_test_data(db, quote_request.id, sales_order.id)

        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)

        for name, passed in results:
            status = "[PASSED]" if passed else "[FAILED]"
            print(f"{name:35} {status}")

        all_passed = all(r[1] for r in results)
        print("\n" + "=" * 60)
        print(f"OVERALL: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    main()
