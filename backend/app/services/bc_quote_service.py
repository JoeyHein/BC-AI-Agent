"""
BC Quote Creation Service
Handles creating and managing quotes in Business Central
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.integrations.bc.client import bc_client
from app.db.models import QuoteRequest, QuoteItem, AuditTrail, BCCustomer, AIDecision
from app.config import settings

logger = logging.getLogger(__name__)


class BCQuoteService:
    """Service for creating and managing BC quotes"""

    def __init__(self):
        self.bc_client = bc_client

    def create_quote_in_bc(
        self,
        db: Session,
        quote_request: QuoteRequest,
        user_id: str,
        approved_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a sales quote in Business Central from a quote request

        Args:
            db: Database session
            quote_request: QuoteRequest object
            user_id: User creating the quote
            approved_by: User who approved (if different)

        Returns:
            Dict with BC quote data and status
        """
        logger.info(f"Creating BC quote for QuoteRequest {quote_request.id}")

        try:
            # Step 1: Find or create BC customer
            bc_customer = self._find_or_create_customer(db, quote_request)

            # Step 2: Build quote data
            quote_data = self._build_quote_data(quote_request, bc_customer)

            # Step 3: Create quote in BC
            bc_quote = self.bc_client.create_sales_quote(quote_data)

            # Step 4: Add line items if any
            if quote_request.quote_items:
                self._add_quote_lines(db, quote_request, bc_quote)

            # Step 5: Update QuoteRequest with BC quote ID
            quote_request.bc_quote_id = bc_quote.get("number")
            quote_request.status = "bc_created"
            db.commit()

            # Step 6: Create audit trail
            self._create_audit_trail(
                db=db,
                user_id=user_id,
                action="bc_quote_created",
                entity_type="sales_quote",
                entity_id=bc_quote.get("number"),
                details={
                    "quote_request_id": quote_request.id,
                    "customer": quote_request.customer_name,
                    "bc_customer_id": bc_customer.get("bc_customer_id") if bc_customer else None,
                    "approved_by": approved_by,
                    "total_amount": bc_quote.get("totalAmountIncludingTax", 0)
                }
            )

            logger.info(f"✅ BC quote created: {bc_quote.get('number')}")

            return {
                "success": True,
                "bc_quote_number": bc_quote.get("number"),
                "bc_quote_id": bc_quote.get("id"),
                "bc_customer_id": bc_quote.get("customerId"),
                "total_amount": bc_quote.get("totalAmountIncludingTax", 0),
                "bc_quote": bc_quote
            }

        except Exception as e:
            logger.error(f"Failed to create BC quote: {e}", exc_info=True)

            # Update quote request status
            quote_request.status = "bc_creation_failed"
            db.commit()

            # Create audit trail for failure
            self._create_audit_trail(
                db=db,
                user_id=user_id,
                action="bc_quote_creation_failed",
                entity_type="quote_request",
                entity_id=str(quote_request.id),
                details={
                    "error": str(e),
                    "customer": quote_request.customer_name
                }
            )

            return {
                "success": False,
                "error": str(e),
                "quote_request_id": quote_request.id
            }

    def _find_or_create_customer(
        self,
        db: Session,
        quote_request: QuoteRequest
    ) -> Optional[Dict[str, Any]]:
        """
        Find existing BC customer or return None (manager will select during approval)

        In the future, this can auto-create customers if needed
        """
        if not quote_request.contact_email:
            return None

        # Check if we have a cached customer
        cached_customer = db.query(BCCustomer).filter(
            BCCustomer.email == quote_request.contact_email
        ).first()

        if cached_customer:
            logger.info(f"Found cached BC customer: {cached_customer.bc_customer_id}")
            return {
                "bc_customer_id": cached_customer.bc_customer_id,
                "company_name": cached_customer.company_name
            }

        # Try to search BC for customer by email
        try:
            # BC API doesn't support email search well, so search by name
            if quote_request.customer_name:
                bc_customers = self.bc_client.search_customers(quote_request.customer_name)

                if bc_customers:
                    # Return first match (manager can override during approval)
                    customer = bc_customers[0]
                    logger.info(f"Found BC customer by name search: {customer.get('displayName')}")

                    # Cache it
                    self._cache_customer(db, customer, quote_request.contact_email)

                    return {
                        "bc_customer_id": customer.get("id"),
                        "company_name": customer.get("displayName")
                    }
        except Exception as e:
            logger.warning(f"Error searching for BC customer: {e}")

        return None

    def _cache_customer(
        self,
        db: Session,
        bc_customer_data: Dict[str, Any],
        email: str
    ):
        """Cache BC customer data for faster lookups"""
        try:
            cached = BCCustomer(
                bc_customer_id=bc_customer_data.get("id"),
                company_name=bc_customer_data.get("displayName"),
                email=email,
                phone=bc_customer_data.get("phoneNumber"),
                last_synced=datetime.utcnow()
            )
            db.add(cached)
            db.commit()
            logger.info(f"Cached BC customer: {cached.company_name}")
        except Exception as e:
            logger.warning(f"Failed to cache customer: {e}")
            db.rollback()

    def _build_quote_data(
        self,
        quote_request: QuoteRequest,
        bc_customer: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Build BC quote data structure

        Note: Manager must select customer during approval if not found
        """
        quote_data = {
            "customerName": quote_request.customer_name or "Unknown Customer"
        }

        # Add customer ID if found
        if bc_customer and bc_customer.get("bc_customer_id"):
            quote_data["customerId"] = bc_customer["bc_customer_id"]

        # Add parsed data as notes/description
        if quote_request.parsed_data:
            notes = []
            notes.append(f"Email from: {quote_request.contact_email}")

            # Add door specs summary
            if quote_request.door_specs:
                doors = quote_request.door_specs.get("doors", [])
                notes.append(f"Doors requested: {len(doors)}")

            quote_data["salespersonCode"] = "AI-AGENT"  # Track AI-generated quotes

        return quote_data

    def _add_quote_lines(
        self,
        db: Session,
        quote_request: QuoteRequest,
        bc_quote: Dict[str, Any]
    ):
        """
        Add line items to BC quote

        Note: Currently managers add line items manually during approval
        In the future, this can auto-add items from QuoteItem table
        """
        bc_quote_id = bc_quote.get("id")

        for item in quote_request.quote_items:
            try:
                if not item.product_code:
                    logger.warning(f"Skipping item {item.id} - no product code")
                    continue

                line_data = {
                    "itemId": item.product_code,
                    "description": item.description or "",
                    "quantity": item.quantity,
                    "unitPrice": float(item.unit_price) if item.unit_price else 0
                }

                self.bc_client.add_quote_line(bc_quote_id, line_data)
                logger.info(f"Added line item: {item.product_code} x{item.quantity}")

            except Exception as e:
                logger.error(f"Failed to add line item {item.id}: {e}")

    def _create_audit_trail(
        self,
        db: Session,
        user_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        details: Dict[str, Any]
    ):
        """Create audit trail entry"""
        try:
            audit = AuditTrail(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
                timestamp=datetime.utcnow()
            )
            db.add(audit)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to create audit trail: {e}")
            db.rollback()

    def approve_quote_request(
        self,
        db: Session,
        quote_request_id: int,
        user_id: str,
        notes: Optional[str] = None,
        customer_id: Optional[str] = None,
        line_items: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Approve a quote request and optionally create in BC

        Args:
            db: Database session
            quote_request_id: QuoteRequest ID
            user_id: User approving
            notes: Approval notes
            customer_id: BC customer ID (if manager selected one)
            line_items: Manual line items added by manager

        Returns:
            Approval result
        """
        quote_request = db.query(QuoteRequest).filter(
            QuoteRequest.id == quote_request_id
        ).first()

        if not quote_request:
            return {"success": False, "error": "Quote request not found"}

        # Update status
        quote_request.status = "approved"
        db.commit()

        # Create audit trail
        self._create_audit_trail(
            db=db,
            user_id=user_id,
            action="quote_approved",
            entity_type="quote_request",
            entity_id=str(quote_request_id),
            details={
                "customer": quote_request.customer_name,
                "notes": notes,
                "customer_id_override": customer_id
            }
        )

        logger.info(f"Quote request {quote_request_id} approved by {user_id}")

        return {
            "success": True,
            "quote_request_id": quote_request_id,
            "status": "approved",
            "message": "Quote approved successfully"
        }

    def reject_quote_request(
        self,
        db: Session,
        quote_request_id: int,
        user_id: str,
        reason: str
    ) -> Dict[str, Any]:
        """Reject a quote request"""
        quote_request = db.query(QuoteRequest).filter(
            QuoteRequest.id == quote_request_id
        ).first()

        if not quote_request:
            return {"success": False, "error": "Quote request not found"}

        # Update status
        quote_request.status = "rejected"
        db.commit()

        # Create audit trail
        self._create_audit_trail(
            db=db,
            user_id=user_id,
            action="quote_rejected",
            entity_type="quote_request",
            entity_id=str(quote_request_id),
            details={
                "customer": quote_request.customer_name,
                "reason": reason
            }
        )

        logger.info(f"Quote request {quote_request_id} rejected by {user_id}: {reason}")

        return {
            "success": True,
            "quote_request_id": quote_request_id,
            "status": "rejected",
            "message": "Quote rejected"
        }


# Global instance
bc_quote_service = BCQuoteService()
