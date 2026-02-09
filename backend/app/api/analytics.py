"""
Analytics API Endpoints
AI-powered quote analysis, customer insights, and demand forecasting.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
import logging
from sqlalchemy.orm import Session

from app.services.quote_analysis_service import quote_analysis_service
from app.services.memory_service import get_memory_service
from app.db.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ==================== Item Analysis ====================

@router.get("/items/frequency")
async def get_item_frequency(
    company_id: Optional[str] = Query(None, description="BC Company ID (optional)")
):
    """
    Get item frequency analysis - which items are most frequently quoted.

    Returns:
    - Top quoted items ranked by frequency
    - Revenue per item
    - Average quantities
    """
    try:
        result = quote_analysis_service.analyze_item_frequency(company_id)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error in item frequency analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/items/affinity")
async def get_item_affinity(
    company_id: Optional[str] = Query(None, description="BC Company ID (optional)"),
    min_support: int = Query(2, description="Minimum quotes where pair must appear together")
):
    """
    Get item affinity analysis - which items are frequently quoted together.

    This is market basket analysis that identifies:
    - Items commonly purchased together
    - Association strength (lift score)
    - Confidence metrics for recommendations

    Use this for:
    - Cross-selling suggestions
    - Bundle creation
    - Quote line suggestions
    """
    try:
        result = quote_analysis_service.analyze_item_affinity(company_id, min_support)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error in item affinity analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Customer Analysis ====================

@router.get("/customers/preferences")
async def get_customer_preferences(
    company_id: Optional[str] = Query(None, description="BC Company ID (optional)")
):
    """
    Get customer preference analysis - buying patterns and top customers.

    Returns:
    - Customer rankings by total value
    - Quote frequency per customer
    - Top items per customer
    - Average order value
    """
    try:
        result = quote_analysis_service.analyze_customer_preferences(company_id)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error in customer preference analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customers/{customer_number}/recommendations")
async def get_customer_recommendations(
    customer_number: str,
    company_id: Optional[str] = Query(None, description="BC Company ID (optional)")
):
    """
    Get personalized product recommendations for a specific customer.

    Based on:
    - Customer's purchase history
    - Item affinity analysis (what similar customers buy)
    - Items frequently purchased together with their orders

    Use this for:
    - Upselling suggestions during quote creation
    - Personalized marketing
    - Proactive outreach
    """
    try:
        result = quote_analysis_service.get_customer_recommendations(customer_number, company_id)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error getting customer recommendations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Pricing Analysis ====================

@router.get("/pricing/trends")
async def get_pricing_trends(
    company_id: Optional[str] = Query(None, description="BC Company ID (optional)")
):
    """
    Get pricing trend analysis across quotes.

    Returns:
    - Average and median quote values
    - Items with high price variance
    - Price ranges per item

    Use this for:
    - Identifying pricing inconsistencies
    - Margin optimization
    - Discount pattern detection
    """
    try:
        result = quote_analysis_service.analyze_pricing_trends(company_id)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error in pricing trend analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Demand Forecasting ====================

@router.get("/demand/forecast")
async def get_demand_forecast(
    company_id: Optional[str] = Query(None, description="BC Company ID (optional)"),
    lookback_days: int = Query(90, description="Days to look back for comparison")
):
    """
    Get demand forecasting based on quote history.

    Compares recent quote activity to historical patterns to identify:
    - Rising demand items (trending up)
    - Falling demand items (trending down)
    - Stable items

    Use this for:
    - Inventory planning
    - Production scheduling
    - Purchasing decisions
    """
    try:
        result = quote_analysis_service.forecast_demand(company_id, lookback_days)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error in demand forecasting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Full Report ====================

@router.get("/report/full")
async def get_full_analysis_report(
    company_id: Optional[str] = Query(None, description="BC Company ID (optional)")
):
    """
    Generate comprehensive analysis report combining all insights.

    Includes:
    - Item frequency analysis
    - Item affinity (market basket) analysis
    - Customer preferences and rankings
    - Pricing trends
    - Demand forecasting

    This is a heavy operation - cache results on the frontend.
    """
    try:
        result = quote_analysis_service.generate_full_report(company_id)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error generating full report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Dashboard Summary ====================

@router.get("/dashboard/summary")
async def get_dashboard_summary(
    company_id: Optional[str] = Query(None, description="BC Company ID (optional)")
):
    """
    Get a lightweight summary for dashboard display.

    Returns key metrics without full detail:
    - Total quotes analyzed
    - Top 5 items
    - Top 5 customers
    - Key statistics
    """
    try:
        # Get lightweight data
        freq = quote_analysis_service.analyze_item_frequency(company_id)
        customers = quote_analysis_service.analyze_customer_preferences(company_id)
        pricing = quote_analysis_service.analyze_pricing_trends(company_id)

        return {
            "success": True,
            "data": {
                "quotes_analyzed": freq['total_quotes_analyzed'],
                "unique_items": freq['unique_items'],
                "unique_customers": customers['total_customers'],
                "avg_quote_value": pricing['avg_quote_value'],
                "median_quote_value": pricing['median_quote_value'],
                "top_items": freq['top_items'][:5],
                "top_customers": [
                    {
                        "customer_number": c['customer_number'],
                        "customer_name": c['customer_name'],
                        "total_value": c['total_value'],
                        "quote_count": c['quote_count']
                    }
                    for c in customers['top_customers'][:5]
                ],
                "analysis_date": freq['analysis_date']
            }
        }
    except Exception as e:
        logger.error(f"Error getting dashboard summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AI Learning Analytics ====================

@router.get("/learning/summary")
async def get_learning_summary(db: Session = Depends(get_db)):
    """
    Get comprehensive AI learning system summary.

    Returns:
    - Example library statistics (total, verified, unverified)
    - Knowledge base stats by type (door models, customer prefs, patterns)
    - Recent feedback summary (approved, corrected, rejected rates)
    - Top correction patterns (what the AI commonly gets wrong)
    - Customer learning stats (known customers, repeat customers)

    Use this for:
    - Monitoring AI performance over time
    - Identifying areas needing more training
    - Understanding customer patterns
    """
    try:
        memory_service = get_memory_service(db)
        summary = memory_service.get_learning_summary()
        return {
            "success": True,
            "data": summary
        }
    except Exception as e:
        logger.error(f"Error getting learning summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning/correction-patterns")
async def get_correction_patterns(
    limit: int = Query(20, description="Maximum patterns to return"),
    db: Session = Depends(get_db)
):
    """
    Get detailed correction patterns - what the AI commonly gets wrong.

    Returns list of fields that are frequently corrected, with:
    - Field name and path
    - Correction count
    - Types of corrections (value added, replaced, etc.)
    - Recent examples

    Use this to understand AI weaknesses and improve prompts.
    """
    try:
        from app.db.models import DomainKnowledge, KnowledgeType
        from sqlalchemy import desc

        patterns = db.query(DomainKnowledge).filter(
            DomainKnowledge.entity.like("field_correction_%")
        ).order_by(desc(DomainKnowledge.confidence)).limit(limit).all()

        result = []
        for p in patterns:
            data = p.pattern_data or {}
            result.append({
                "field": data.get("field", p.entity),
                "correction_count": data.get("correction_count", 0),
                "correction_types": data.get("correction_types", []),
                "last_seen": data.get("last_seen"),
                "first_seen": data.get("first_seen"),
                "confidence": p.confidence
            })

        return {
            "success": True,
            "data": {
                "patterns": result,
                "total_patterns": len(patterns)
            }
        }
    except Exception as e:
        logger.error(f"Error getting correction patterns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning/customer-insights")
async def get_customer_insights(
    limit: int = Query(20, description="Maximum customers to return"),
    db: Session = Depends(get_db)
):
    """
    Get customer learning insights - what we know about each customer.

    Returns list of known customers with:
    - Quote history count
    - Preferred door models
    - Common sizes ordered
    - Installation preferences

    Use this for understanding customer patterns and personalization.
    """
    try:
        from app.db.models import DomainKnowledge, KnowledgeType
        from sqlalchemy import desc

        customers = db.query(DomainKnowledge).filter(
            DomainKnowledge.knowledge_type == KnowledgeType.CUSTOMER_PREFERENCE
        ).order_by(desc(DomainKnowledge.confidence)).limit(limit).all()

        result = []
        for c in customers:
            data = c.pattern_data or {}
            result.append({
                "customer_email": c.entity,
                "customer_name": data.get("customer_name"),
                "quote_count": data.get("quote_count", 0),
                "preferred_models": data.get("preferred_models", {}),
                "common_sizes": data.get("common_sizes", []),
                "preferred_colors": data.get("preferred_colors", {}),
                "usually_needs_installation": data.get("usually_needs_installation"),
                "first_seen": data.get("first_seen"),
                "last_quote": data.get("last_quote"),
                "confidence": c.confidence
            })

        return {
            "success": True,
            "data": {
                "customers": result,
                "total_known_customers": len(customers)
            }
        }
    except Exception as e:
        logger.error(f"Error getting customer insights: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning/model-accuracy")
async def get_model_accuracy(db: Session = Depends(get_db)):
    """
    Get parsing accuracy by door model.

    Returns accuracy metrics for each door model we've parsed:
    - Parse count
    - Correct count
    - Accuracy rate

    Use this to identify which models need better training.
    """
    try:
        from app.db.models import DomainKnowledge, KnowledgeType

        models = db.query(DomainKnowledge).filter(
            DomainKnowledge.knowledge_type == KnowledgeType.DOOR_MODEL
        ).all()

        result = []
        for m in models:
            data = m.pattern_data or {}
            if data.get("parse_count"):  # Only include models with accuracy tracking
                result.append({
                    "model": m.entity,
                    "parse_count": data.get("parse_count", 0),
                    "correct_count": data.get("correct_count", 0),
                    "accuracy": data.get("parse_accuracy"),
                    "confidence": m.confidence
                })

        # Sort by parse count (most used first)
        result.sort(key=lambda x: x["parse_count"], reverse=True)

        return {
            "success": True,
            "data": {
                "models": result,
                "total_models_tracked": len(result)
            }
        }
    except Exception as e:
        logger.error(f"Error getting model accuracy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
