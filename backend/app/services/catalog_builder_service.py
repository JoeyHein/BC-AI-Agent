"""
Catalog Builder Agent Service
Pipeline: Extract → Classify → Enrich → Deduplicate → Publish

Extracts items from Business Central, classifies by part-number prefix,
enriches attributes, flags duplicates, and publishes to parts table.
"""

import logging
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import (
    BCStagingItem, CatalogReviewItem, DuplicateCandidate, Part, AppSettings,
)
from app.integrations.bc.client import bc_client
from app.services.bc_part_number_mapper import BCPartNumberMapper

logger = logging.getLogger(__name__)

# Part number prefix → category mapping
PREFIX_CATEGORIES: Dict[str, Tuple[str, str]] = {
    # prefix: (category, subcategory)
    "SP10": ("spring", "galvanized"),
    "SP11": ("spring", "oil_tempered"),
    "SP12": ("spring", "accessory"),
    "SP16": ("spring", "pre_pick"),
    "PN35": ("panel", "TX380"),
    "PN45": ("panel", "TX450_SEC"),
    "PN46": ("panel", "TX450_DEC"),
    "PN47": ("panel", "TX450_20_SEC"),
    "PN48": ("panel", "TX450_20_DEC"),
    "PN55": ("panel", "TX500_SEC"),
    "PN56": ("panel", "TX500_DEC"),
    "PN57": ("panel", "TX500_20_SEC"),
    "PN58": ("panel", "TX500_20_DEC"),
    "PN65": ("panel", "KANATA"),
    "PN95": ("panel", "CRAFT"),
    "TR02": ("track", "2_inch"),
    "TR03": ("track", "3_inch"),
    "SH11": ("shaft", "solid_keyed"),
    "SH12": ("shaft", "tube"),
    "HK01": ("hardware_kit", "residential"),
    "HK02": ("hardware_kit", "commercial"),
    "HK03": ("hardware_kit", "commercial"),
    "HK04": ("hardware_kit", "commercial"),
    "HK05": ("hardware_kit", "commercial"),
    "HK06": ("hardware_kit", "commercial"),
    "FH10": ("hardware", "end_cap"),
    "FH12": ("hardware", "hinge_bracket"),
    "FH15": ("hardware", "roller"),
    "FH17": ("hardware", "strut"),
    "PL10": ("plastic", "weather_strip"),
    "AL": ("aluminum", "misc"),
    "GK": ("glazing_kit", "misc"),
}

# 2-char fallback prefixes (checked if 4-char not matched)
PREFIX_FALLBACK: Dict[str, Tuple[str, str]] = {
    "SP": ("spring", "misc"),
    "PN": ("panel", "misc"),
    "TR": ("track", "misc"),
    "SH": ("shaft", "misc"),
    "HK": ("hardware_kit", "misc"),
    "FH": ("hardware", "misc"),
    "PL": ("plastic", "misc"),
}

# Wire size regex for spring enrichment
_SPRING_RE = re.compile(
    r"^(SP1[016])-(\d{3})(\d{2})-(\d{2})$"
)

# Panel regex
_PANEL_RE = re.compile(
    r"^(PN\d{2})-(\d{2})(\d)(\d{2})-(\d{4})$"
)

mapper = BCPartNumberMapper()


class CatalogBuilderService:
    """Orchestrates the catalog builder pipeline."""

    def run_pipeline(self, db: Session) -> dict:
        """Run the full Extract → Classify → Enrich → Deduplicate → Publish pipeline."""
        run_id = uuid.uuid4().hex[:12]
        logger.info(f"[CatalogBuilder] Starting pipeline run {run_id}")

        stats = {
            "run_id": run_id,
            "extracted": 0,
            "classified": 0,
            "review_queue": 0,
            "enriched": 0,
            "duplicates_found": 0,
            "published": 0,
            "errors": [],
        }

        try:
            stats["extracted"] = self._extract(db, run_id)
            classified, review = self._classify(db, run_id)
            stats["classified"] = classified
            stats["review_queue"] = review
            stats["enriched"] = self._enrich(db, run_id)
            stats["duplicates_found"] = self._deduplicate(db, run_id)
            stats["published"] = self._publish(db, run_id)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"[CatalogBuilder] Pipeline failed: {e}", exc_info=True)
            stats["errors"].append(str(e))

        logger.info(f"[CatalogBuilder] Pipeline {run_id} complete: {stats}")
        return stats

    # ─── EXTRACT ───────────────────────────────────────────────

    def _extract(self, db: Session, run_id: str) -> int:
        """Pull all BC items and insert into bc_staging."""
        logger.info("[CatalogBuilder] Extracting items from BC...")

        try:
            # Paginate through all BC items
            all_items = []
            skip = 0
            page_size = 1000
            while True:
                cid = bc_client.company_id
                result = bc_client._make_request(
                    "GET",
                    f"companies({cid})/items?$top={page_size}&$skip={skip}"
                )
                items = result.get("value", [])
                all_items.extend(items)
                if len(items) < page_size:
                    break
                skip += page_size

            logger.info(f"[CatalogBuilder] Fetched {len(all_items)} items from BC")
        except Exception as e:
            logger.error(f"[CatalogBuilder] BC extraction failed: {e}")
            raise

        count = 0
        for item in all_items:
            item_number = item.get("number", "").strip()
            if not item_number:
                continue

            # Skip if already staged in this run
            existing = db.query(BCStagingItem).filter(
                BCStagingItem.bc_item_number == item_number,
                BCStagingItem.pipeline_run_id == run_id,
            ).first()
            if existing:
                continue

            staging = BCStagingItem(
                bc_item_id=item.get("id", ""),
                bc_item_number=item_number,
                bc_description=item.get("displayName", ""),
                bc_unit_cost=item.get("unitCost"),
                bc_unit_price=item.get("unitPrice"),
                bc_inventory=item.get("inventory"),
                bc_raw_data=item,
                pipeline_run_id=run_id,
                created_at=datetime.utcnow(),
            )
            db.add(staging)
            count += 1

        db.flush()
        logger.info(f"[CatalogBuilder] Staged {count} items")
        return count

    # ─── CLASSIFY ──────────────────────────────────────────────

    def _classify(self, db: Session, run_id: str) -> Tuple[int, int]:
        """Classify staged items by part-number prefix."""
        items = db.query(BCStagingItem).filter(
            BCStagingItem.pipeline_run_id == run_id,
            BCStagingItem.is_processed == False,
        ).all()

        classified = 0
        review_count = 0

        for item in items:
            pn = item.bc_item_number
            category, subcategory = self._classify_item_number(pn)

            if category:
                item.classified_category = category
                item.enriched_attributes = {"subcategory": subcategory}
                classified += 1
            else:
                # Unknown prefix → review queue
                review = CatalogReviewItem(
                    staging_id=item.id,
                    bc_item_number=pn,
                    bc_description=item.bc_description,
                    reason="unknown_prefix",
                    suggested_category=None,
                    created_at=datetime.utcnow(),
                )
                db.add(review)
                item.classified_category = "unknown"
                item.processing_notes = "Sent to review queue (unknown prefix)"
                review_count += 1

        db.flush()
        logger.info(f"[CatalogBuilder] Classified {classified}, review queue {review_count}")
        return classified, review_count

    def _classify_item_number(self, item_number: str) -> Tuple[Optional[str], Optional[str]]:
        """Classify an item number by its prefix."""
        # Try 4-char prefix first
        prefix4 = item_number[:4]
        if prefix4 in PREFIX_CATEGORIES:
            return PREFIX_CATEGORIES[prefix4]

        # Try 2-char fallback
        prefix2 = item_number[:2]
        if prefix2 in PREFIX_FALLBACK:
            return PREFIX_FALLBACK[prefix2]

        # Special cases
        if item_number.startswith("GK"):
            return "glazing_kit", "misc"
        if item_number.startswith("AL"):
            return "aluminum", "misc"

        return None, None

    # ─── ENRICH ────────────────────────────────────────────────

    def _enrich(self, db: Session, run_id: str) -> int:
        """Parse structured attributes from item numbers."""
        items = db.query(BCStagingItem).filter(
            BCStagingItem.pipeline_run_id == run_id,
            BCStagingItem.classified_category != "unknown",
            BCStagingItem.classified_category != None,
        ).all()

        count = 0
        for item in items:
            attrs = self._extract_attributes(item.bc_item_number, item.classified_category)
            if attrs:
                existing = item.enriched_attributes or {}
                existing.update(attrs)
                item.enriched_attributes = existing
                count += 1

        db.flush()
        logger.info(f"[CatalogBuilder] Enriched {count} items")
        return count

    def _extract_attributes(self, item_number: str, category: str) -> Optional[dict]:
        """Extract structured attributes from a part number."""
        if category == "spring":
            return self._parse_spring_attributes(item_number)
        elif category == "panel":
            return self._parse_panel_attributes(item_number)
        elif category == "track":
            return self._parse_track_attributes(item_number)
        elif category == "shaft":
            return self._parse_shaft_attributes(item_number)
        return None

    def _parse_spring_attributes(self, pn: str) -> Optional[dict]:
        """Parse spring part number: SP10-{wire}{coil}-{wind}"""
        m = _SPRING_RE.match(pn)
        if not m:
            return None

        prefix, wire_code, coil_code, wind_code = m.groups()

        # Reverse-lookup wire size
        wire_size = None
        for size, code in mapper.WIRE_SIZE_CODES.items():
            if code == wire_code:
                wire_size = size
                break

        coil_size = None
        for size, code in mapper.COIL_SIZE_CODES.items():
            if code == coil_code:
                coil_size = size
                break

        return {
            "spring_type": prefix,
            "wire_diameter": wire_size,
            "coil_diameter": coil_size,
            "wind_direction": "LH" if wind_code == "01" else "RH",
        }

    def _parse_panel_attributes(self, pn: str) -> Optional[dict]:
        """Parse panel part number: PN{series}-{height}{stamp}{color}-{width}"""
        m = _PANEL_RE.match(pn)
        if not m:
            return None

        series, height, stamp, color_code, width = m.groups()

        # Reverse color lookup
        color_name = None
        for name, code in mapper.COLOR_CODES.items():
            if code == color_code:
                color_name = name
                break

        return {
            "panel_series": series,
            "section_height": int(height),
            "stamp_code": stamp,
            "color_code": color_code,
            "color_name": color_name,
            "width_inches": int(width) if width.isdigit() else None,
        }

    def _parse_track_attributes(self, pn: str) -> Optional[dict]:
        """Parse basic track attributes."""
        attrs = {}
        if pn.startswith("TR02"):
            attrs["track_size"] = "2_inch"
        elif pn.startswith("TR03"):
            attrs["track_size"] = "3_inch"

        if "STDBM" in pn:
            attrs["mount_type"] = "bracket"
            attrs["lift_type"] = "standard"
        elif "STDAM" in pn:
            attrs["mount_type"] = "angle"
            attrs["lift_type"] = "standard"
        elif "VLBM" in pn:
            attrs["mount_type"] = "bracket"
            attrs["lift_type"] = "vertical"

        return attrs if attrs else None

    def _parse_shaft_attributes(self, pn: str) -> Optional[dict]:
        """Parse shaft attributes."""
        attrs = {}
        if pn.startswith("SH11"):
            attrs["shaft_type"] = "solid_keyed"
            attrs["diameter"] = 1.0
        elif pn.startswith("SH12"):
            attrs["shaft_type"] = "tube"
            attrs["diameter"] = 1.0
        return attrs if attrs else None

    # ─── DEDUPLICATE ───────────────────────────────────────────

    def _deduplicate(self, db: Session, run_id: str) -> int:
        """Compare enriched items against existing parts table."""
        staged = db.query(BCStagingItem).filter(
            BCStagingItem.pipeline_run_id == run_id,
            BCStagingItem.classified_category != "unknown",
            BCStagingItem.classified_category != None,
        ).all()

        dup_count = 0
        for item in staged:
            # Check if already in parts table
            existing = db.query(Part).filter(
                Part.bc_item_number == item.bc_item_number
            ).first()

            if existing:
                # Exact SKU match — flag as duplicate
                dup = DuplicateCandidate(
                    item_a_number=existing.bc_item_number,
                    item_b_number=item.bc_item_number,
                    item_a_id=existing.id,
                    similarity_score=1.0,
                    match_reasons=["exact_sku_match"],
                    created_at=datetime.utcnow(),
                )
                db.add(dup)
                item.processing_notes = (item.processing_notes or "") + " [DUPLICATE]"
                dup_count += 1

        db.flush()
        logger.info(f"[CatalogBuilder] Found {dup_count} duplicates")
        return dup_count

    # ─── PUBLISH ───────────────────────────────────────────────

    def _publish(self, db: Session, run_id: str) -> int:
        """Move classified items to parts table with pending_review status."""
        staged = db.query(BCStagingItem).filter(
            BCStagingItem.pipeline_run_id == run_id,
            BCStagingItem.classified_category != "unknown",
            BCStagingItem.classified_category != None,
            BCStagingItem.is_processed == False,
        ).all()

        count = 0
        for item in staged:
            # Skip if already in parts table (duplicate)
            existing = db.query(Part).filter(
                Part.bc_item_number == item.bc_item_number
            ).first()
            if existing:
                item.is_processed = True
                item.processed_at = datetime.utcnow()
                continue

            attrs = item.enriched_attributes or {}
            subcategory = attrs.pop("subcategory", None)

            part = Part(
                bc_item_id=item.bc_item_id,
                bc_item_number=item.bc_item_number,
                bc_description=item.bc_description,
                category=item.classified_category,
                subcategory=subcategory,
                attributes=attrs if attrs else None,
                unit_cost=item.bc_unit_cost,
                retail_price=item.bc_unit_price,
                catalog_status="active",
                created_at=datetime.utcnow(),
            )
            db.add(part)
            item.is_processed = True
            item.processed_at = datetime.utcnow()
            count += 1

        db.flush()
        logger.info(f"[CatalogBuilder] Published {count} items to parts table")
        return count

    # ─── QUERY HELPERS ─────────────────────────────────────────

    def get_staging_items(self, db: Session, run_id: Optional[str] = None,
                          processed: Optional[bool] = None,
                          skip: int = 0, limit: int = 50) -> List[BCStagingItem]:
        """List staged items with optional filters."""
        q = db.query(BCStagingItem)
        if run_id:
            q = q.filter(BCStagingItem.pipeline_run_id == run_id)
        if processed is not None:
            q = q.filter(BCStagingItem.is_processed == processed)
        return q.order_by(BCStagingItem.id.desc()).offset(skip).limit(limit).all()

    def get_review_queue(self, db: Session, resolved: Optional[bool] = None,
                         skip: int = 0, limit: int = 50) -> List[CatalogReviewItem]:
        """List review queue items."""
        q = db.query(CatalogReviewItem)
        if resolved is not None:
            q = q.filter(CatalogReviewItem.is_resolved == resolved)
        return q.order_by(CatalogReviewItem.id.desc()).offset(skip).limit(limit).all()

    def resolve_review_item(self, db: Session, review_id: int,
                             category: str, attributes: Optional[dict],
                             user_id: int) -> CatalogReviewItem:
        """Resolve a review queue item."""
        review = db.query(CatalogReviewItem).get(review_id)
        if not review:
            raise ValueError(f"Review item {review_id} not found")

        review.is_resolved = True
        review.resolved_category = category
        review.resolved_attributes = attributes
        review.resolved_by = user_id
        review.resolved_at = datetime.utcnow()

        # If staging item exists, update it and create a Part
        if review.staging_id:
            staging = db.query(BCStagingItem).get(review.staging_id)
            if staging and not staging.is_processed:
                staging.classified_category = category
                staging.enriched_attributes = attributes
                staging.is_processed = True
                staging.processed_at = datetime.utcnow()

                # Create part from resolved review
                part = Part(
                    bc_item_id=staging.bc_item_id,
                    bc_item_number=staging.bc_item_number,
                    bc_description=staging.bc_description,
                    category=category,
                    attributes=attributes,
                    unit_cost=staging.bc_unit_cost,
                    retail_price=staging.bc_unit_price,
                    catalog_status="active",
                    created_at=datetime.utcnow(),
                )
                db.add(part)

        db.flush()
        return review

    def get_duplicates(self, db: Session, resolved: Optional[bool] = None,
                       skip: int = 0, limit: int = 50) -> List[DuplicateCandidate]:
        """List duplicate candidates."""
        q = db.query(DuplicateCandidate)
        if resolved is not None:
            q = q.filter(DuplicateCandidate.is_resolved == resolved)
        return q.order_by(DuplicateCandidate.id.desc()).offset(skip).limit(limit).all()

    def get_parts(self, db: Session, category: Optional[str] = None,
                  status: Optional[str] = None, search: Optional[str] = None,
                  skip: int = 0, limit: int = 50) -> List[Part]:
        """Browse published catalog parts."""
        q = db.query(Part)
        if category:
            q = q.filter(Part.category == category)
        if status:
            q = q.filter(Part.catalog_status == status)
        if search:
            q = q.filter(
                (Part.bc_item_number.ilike(f"%{search}%")) |
                (Part.bc_description.ilike(f"%{search}%"))
            )
        return q.order_by(Part.bc_item_number).offset(skip).limit(limit).all()

    def get_stats(self, db: Session) -> dict:
        """Pipeline statistics."""
        total_staged = db.query(BCStagingItem).count()
        processed = db.query(BCStagingItem).filter(BCStagingItem.is_processed == True).count()
        total_parts = db.query(Part).count()
        active_parts = db.query(Part).filter(Part.catalog_status == "active").count()
        pending_parts = db.query(Part).filter(Part.catalog_status == "pending_review").count()
        review_pending = db.query(CatalogReviewItem).filter(CatalogReviewItem.is_resolved == False).count()
        duplicates_pending = db.query(DuplicateCandidate).filter(DuplicateCandidate.is_resolved == False).count()

        return {
            "staging": {"total": total_staged, "processed": processed, "unprocessed": total_staged - processed},
            "parts": {"total": total_parts, "active": active_parts, "pending_review": pending_parts},
            "review_queue": {"pending": review_pending},
            "duplicates": {"pending": duplicates_pending},
        }


# Global instance
catalog_builder_service = CatalogBuilderService()
