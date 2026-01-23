"""
Quote Analysis Service
AI-powered analysis of historical quote data for pattern detection,
customer preferences, item affinity, and demand forecasting.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from itertools import combinations
import statistics

from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)


class QuoteAnalysisService:
    """
    Analyzes historical quote data to extract business intelligence:
    - Item frequency and popularity
    - Item affinity (frequently quoted together)
    - Customer preferences and buying patterns
    - Pricing trends
    - Demand forecasting
    """

    def __init__(self):
        self.bc_client = bc_client
        self._cache = {}
        self._cache_timestamp = None
        self._cache_ttl = timedelta(minutes=30)

    # ==================== Data Collection ====================

    def fetch_quote_data(self, company_id: Optional[str] = None,
                         max_quotes: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch quotes with their line items from BC.
        Returns enriched quote data ready for analysis.
        """
        logger.info(f"Fetching quote data (max {max_quotes} quotes)")

        quotes = self.bc_client.get_sales_quotes(
            company_id=company_id,
            top=max_quotes
        )

        enriched_quotes = []
        for quote in quotes:
            try:
                lines = self.bc_client.get_quote_lines(
                    quote['id'],
                    company_id=company_id
                )

                enriched_quotes.append({
                    'id': quote['id'],
                    'number': quote['number'],
                    'customer_id': quote.get('customerId'),
                    'customer_number': quote.get('customerNumber'),
                    'customer_name': quote.get('customerName'),
                    'document_date': quote.get('documentDate'),
                    'total_amount': quote.get('totalAmountIncludingTax', 0),
                    'status': quote.get('status'),
                    'salesperson': quote.get('salesperson'),
                    'lines': [
                        {
                            'item_number': line.get('lineObjectNumber'),
                            'item_id': line.get('itemId'),
                            'description': line.get('description'),
                            'quantity': line.get('quantity', 0),
                            'unit_price': line.get('unitPrice', 0),
                            'line_amount': line.get('amountIncludingTax', 0),
                            'line_type': line.get('lineType')
                        }
                        for line in lines
                        if line.get('lineObjectNumber')  # Skip empty lines
                    ]
                })
            except Exception as e:
                logger.warning(f"Error fetching lines for quote {quote['number']}: {e}")

        logger.info(f"Fetched {len(enriched_quotes)} quotes with line data")
        return enriched_quotes

    def _get_cached_data(self, company_id: Optional[str] = None) -> List[Dict]:
        """Get cached quote data or fetch fresh if expired"""
        cache_key = company_id or 'default'

        if (self._cache_timestamp and
            datetime.utcnow() - self._cache_timestamp < self._cache_ttl and
            cache_key in self._cache):
            return self._cache[cache_key]

        data = self.fetch_quote_data(company_id)
        self._cache[cache_key] = data
        self._cache_timestamp = datetime.utcnow()
        return data

    # ==================== Item Analysis ====================

    def analyze_item_frequency(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze which items are most frequently quoted.
        Returns item popularity rankings and statistics.
        """
        quotes = self._get_cached_data(company_id)

        item_counts = Counter()
        item_quantities = defaultdict(list)
        item_revenues = defaultdict(float)
        item_descriptions = {}

        for quote in quotes:
            for line in quote['lines']:
                item_num = line['item_number']
                if item_num:
                    item_counts[item_num] += 1
                    item_quantities[item_num].append(line['quantity'])
                    item_revenues[item_num] += line['line_amount']
                    if item_num not in item_descriptions:
                        item_descriptions[item_num] = line['description']

        # Build ranked list
        ranked_items = []
        for item_num, count in item_counts.most_common(50):
            quantities = item_quantities[item_num]
            ranked_items.append({
                'item_number': item_num,
                'description': item_descriptions.get(item_num, ''),
                'quote_count': count,
                'total_quantity': sum(quantities),
                'avg_quantity': statistics.mean(quantities) if quantities else 0,
                'total_revenue': round(item_revenues[item_num], 2),
                'avg_revenue_per_quote': round(item_revenues[item_num] / count, 2) if count else 0
            })

        return {
            'total_quotes_analyzed': len(quotes),
            'unique_items': len(item_counts),
            'top_items': ranked_items[:20],
            'full_ranking': ranked_items,
            'analysis_date': datetime.utcnow().isoformat()
        }

    def analyze_item_affinity(self, company_id: Optional[str] = None,
                              min_support: int = 2) -> Dict[str, Any]:
        """
        Analyze which items are frequently quoted together (market basket analysis).
        Uses association rule mining concepts.

        Args:
            min_support: Minimum number of quotes where pair must appear together
        """
        quotes = self._get_cached_data(company_id)

        # Count item pairs
        pair_counts = Counter()
        item_counts = Counter()

        for quote in quotes:
            items = [line['item_number'] for line in quote['lines'] if line['item_number']]
            unique_items = list(set(items))

            # Count individual items
            for item in unique_items:
                item_counts[item] += 1

            # Count pairs (combinations of 2)
            if len(unique_items) >= 2:
                for pair in combinations(sorted(unique_items), 2):
                    pair_counts[pair] += 1

        # Calculate confidence and lift for frequent pairs
        total_quotes = len(quotes)
        associations = []

        for (item_a, item_b), pair_count in pair_counts.most_common(100):
            if pair_count < min_support:
                continue

            count_a = item_counts[item_a]
            count_b = item_counts[item_b]

            # Support: How often the pair appears together
            support = pair_count / total_quotes if total_quotes else 0

            # Confidence A->B: Given A, how often is B also present
            confidence_ab = pair_count / count_a if count_a else 0

            # Confidence B->A: Given B, how often is A also present
            confidence_ba = pair_count / count_b if count_b else 0

            # Lift: How much more likely they appear together vs independently
            expected = (count_a / total_quotes) * (count_b / total_quotes) * total_quotes
            lift = pair_count / expected if expected else 0

            associations.append({
                'item_a': item_a,
                'item_b': item_b,
                'pair_count': pair_count,
                'support': round(support, 4),
                'confidence_a_to_b': round(confidence_ab, 4),
                'confidence_b_to_a': round(confidence_ba, 4),
                'lift': round(lift, 2),
                'recommendation': 'Strong' if lift > 2 else 'Moderate' if lift > 1.2 else 'Weak'
            })

        # Sort by lift (strongest associations first)
        associations.sort(key=lambda x: x['lift'], reverse=True)

        return {
            'total_quotes_analyzed': len(quotes),
            'unique_items': len(item_counts),
            'pairs_analyzed': len(pair_counts),
            'strong_associations': [a for a in associations if a['lift'] > 2][:20],
            'all_associations': associations[:50],
            'analysis_date': datetime.utcnow().isoformat()
        }

    # ==================== Customer Analysis ====================

    def analyze_customer_preferences(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze customer buying patterns and preferences.
        Returns customer-specific insights.
        """
        quotes = self._get_cached_data(company_id)

        customer_data = defaultdict(lambda: {
            'name': '',
            'quote_count': 0,
            'total_value': 0,
            'items': Counter(),
            'avg_order_value': 0,
            'last_quote_date': None
        })

        for quote in quotes:
            cust_num = quote['customer_number']
            if not cust_num:
                continue

            customer_data[cust_num]['name'] = quote['customer_name']
            customer_data[cust_num]['quote_count'] += 1
            customer_data[cust_num]['total_value'] += quote['total_amount']

            quote_date = quote.get('document_date')
            if quote_date:
                current_last = customer_data[cust_num]['last_quote_date']
                if not current_last or quote_date > current_last:
                    customer_data[cust_num]['last_quote_date'] = quote_date

            for line in quote['lines']:
                if line['item_number']:
                    customer_data[cust_num]['items'][line['item_number']] += line['quantity']

        # Build customer profiles
        customer_profiles = []
        for cust_num, data in customer_data.items():
            top_items = data['items'].most_common(10)
            customer_profiles.append({
                'customer_number': cust_num,
                'customer_name': data['name'],
                'quote_count': data['quote_count'],
                'total_value': round(data['total_value'], 2),
                'avg_quote_value': round(data['total_value'] / data['quote_count'], 2) if data['quote_count'] else 0,
                'last_quote_date': data['last_quote_date'],
                'top_items': [{'item': item, 'quantity': qty} for item, qty in top_items],
                'unique_items_ordered': len(data['items'])
            })

        # Sort by total value (best customers first)
        customer_profiles.sort(key=lambda x: x['total_value'], reverse=True)

        return {
            'total_customers': len(customer_profiles),
            'total_quotes_analyzed': len(quotes),
            'top_customers': customer_profiles[:20],
            'all_customers': customer_profiles,
            'analysis_date': datetime.utcnow().isoformat()
        }

    def get_customer_recommendations(self, customer_number: str,
                                     company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get personalized product recommendations for a specific customer
        based on their history and similar customers.
        """
        quotes = self._get_cached_data(company_id)

        # Get customer's ordered items
        customer_items = set()
        customer_quotes = []

        for quote in quotes:
            if quote['customer_number'] == customer_number:
                customer_quotes.append(quote)
                for line in quote['lines']:
                    if line['item_number']:
                        customer_items.add(line['item_number'])

        if not customer_items:
            return {
                'customer_number': customer_number,
                'recommendations': [],
                'message': 'No quote history found for this customer'
            }

        # Get item affinities
        affinity = self.analyze_item_affinity(company_id)

        # Find items frequently bought with customer's items but not yet ordered
        recommendations = []
        seen_items = set()

        for assoc in affinity['all_associations']:
            item_a, item_b = assoc['item_a'], assoc['item_b']

            # If customer has item_a but not item_b
            if item_a in customer_items and item_b not in customer_items and item_b not in seen_items:
                recommendations.append({
                    'item': item_b,
                    'reason': f"Frequently ordered with {item_a}",
                    'confidence': assoc['confidence_a_to_b'],
                    'lift': assoc['lift']
                })
                seen_items.add(item_b)

            # If customer has item_b but not item_a
            if item_b in customer_items and item_a not in customer_items and item_a not in seen_items:
                recommendations.append({
                    'item': item_a,
                    'reason': f"Frequently ordered with {item_b}",
                    'confidence': assoc['confidence_b_to_a'],
                    'lift': assoc['lift']
                })
                seen_items.add(item_a)

        # Sort by lift
        recommendations.sort(key=lambda x: x['lift'], reverse=True)

        return {
            'customer_number': customer_number,
            'customer_name': customer_quotes[0]['customer_name'] if customer_quotes else '',
            'items_ordered': list(customer_items),
            'quote_count': len(customer_quotes),
            'recommendations': recommendations[:15],
            'analysis_date': datetime.utcnow().isoformat()
        }

    # ==================== Pricing Analysis ====================

    def analyze_pricing_trends(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze pricing patterns and trends across quotes.
        """
        quotes = self._get_cached_data(company_id)

        item_prices = defaultdict(list)

        for quote in quotes:
            quote_date = quote.get('document_date', '')
            for line in quote['lines']:
                if line['item_number'] and line['unit_price'] > 0:
                    item_prices[line['item_number']].append({
                        'price': line['unit_price'],
                        'quantity': line['quantity'],
                        'date': quote_date
                    })

        pricing_analysis = []
        for item_num, prices in item_prices.items():
            if len(prices) >= 2:
                price_values = [p['price'] for p in prices]
                pricing_analysis.append({
                    'item_number': item_num,
                    'quote_count': len(prices),
                    'min_price': min(price_values),
                    'max_price': max(price_values),
                    'avg_price': round(statistics.mean(price_values), 2),
                    'price_std_dev': round(statistics.stdev(price_values), 2) if len(price_values) > 1 else 0,
                    'price_variance_pct': round((max(price_values) - min(price_values)) / min(price_values) * 100, 1) if min(price_values) > 0 else 0
                })

        # Sort by variance (items with most price variation)
        pricing_analysis.sort(key=lambda x: x['price_variance_pct'], reverse=True)

        # Calculate overall statistics
        all_quote_values = [q['total_amount'] for q in quotes if q['total_amount'] > 0]

        return {
            'total_quotes_analyzed': len(quotes),
            'items_with_pricing_data': len(pricing_analysis),
            'avg_quote_value': round(statistics.mean(all_quote_values), 2) if all_quote_values else 0,
            'median_quote_value': round(statistics.median(all_quote_values), 2) if all_quote_values else 0,
            'items_with_high_variance': [p for p in pricing_analysis if p['price_variance_pct'] > 10][:20],
            'all_pricing': pricing_analysis[:50],
            'analysis_date': datetime.utcnow().isoformat()
        }

    # ==================== Demand Forecasting ====================

    def forecast_demand(self, company_id: Optional[str] = None,
                       lookback_days: int = 90) -> Dict[str, Any]:
        """
        Simple demand forecasting based on historical quote patterns.
        Identifies trending items and predicts future demand.
        """
        quotes = self._get_cached_data(company_id)

        # Parse dates and filter recent quotes
        cutoff_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

        recent_quotes = []
        older_quotes = []

        for quote in quotes:
            quote_date = quote.get('document_date', '')
            if quote_date >= cutoff_date:
                recent_quotes.append(quote)
            else:
                older_quotes.append(quote)

        # Count items in recent vs older periods
        recent_items = Counter()
        older_items = Counter()

        for quote in recent_quotes:
            for line in quote['lines']:
                if line['item_number']:
                    recent_items[line['item_number']] += line['quantity']

        for quote in older_quotes:
            for line in quote['lines']:
                if line['item_number']:
                    older_items[line['item_number']] += line['quantity']

        # Calculate trends
        trends = []
        all_items = set(recent_items.keys()) | set(older_items.keys())

        for item in all_items:
            recent_qty = recent_items.get(item, 0)
            older_qty = older_items.get(item, 0)

            if older_qty > 0:
                change_pct = ((recent_qty - older_qty) / older_qty) * 100
            elif recent_qty > 0:
                change_pct = 100  # New item
            else:
                change_pct = 0

            trends.append({
                'item_number': item,
                'recent_quantity': recent_qty,
                'older_quantity': older_qty,
                'change_pct': round(change_pct, 1),
                'trend': 'Rising' if change_pct > 20 else 'Falling' if change_pct < -20 else 'Stable'
            })

        # Sort by change percentage
        rising = sorted([t for t in trends if t['trend'] == 'Rising'],
                       key=lambda x: x['change_pct'], reverse=True)
        falling = sorted([t for t in trends if t['trend'] == 'Falling'],
                        key=lambda x: x['change_pct'])

        return {
            'lookback_days': lookback_days,
            'recent_quotes': len(recent_quotes),
            'older_quotes': len(older_quotes),
            'rising_items': rising[:15],
            'falling_items': falling[:15],
            'stable_items_count': len([t for t in trends if t['trend'] == 'Stable']),
            'analysis_date': datetime.utcnow().isoformat()
        }

    # ==================== Comprehensive Report ====================

    def generate_full_report(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a comprehensive analysis report combining all insights.
        """
        logger.info("Generating full quote analysis report")

        return {
            'item_frequency': self.analyze_item_frequency(company_id),
            'item_affinity': self.analyze_item_affinity(company_id),
            'customer_preferences': self.analyze_customer_preferences(company_id),
            'pricing_trends': self.analyze_pricing_trends(company_id),
            'demand_forecast': self.forecast_demand(company_id),
            'generated_at': datetime.utcnow().isoformat()
        }


# Global instance
quote_analysis_service = QuoteAnalysisService()
