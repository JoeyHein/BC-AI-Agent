import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useCart } from '../../contexts/CartContext';
import { useCustomerAuth } from '../../contexts/CustomerAuthContext';
import { cartApi } from '../../api/customerClient';

export default function PartsCart() {
  const { items, bcQuoteId, bcQuoteNumber, quotePricing, removeItem, updateQuantity, clearCart, setQuoteResult, clearQuote } = useCart();
  const { isBCLinked } = useCustomerAuth();
  const [loading, setLoading] = useState(false);
  const [ordering, setOrdering] = useState(false);
  const [error, setError] = useState(null);
  const [linePricing, setLinePricing] = useState(null);
  const [orderResult, setOrderResult] = useState(null);

  async function handleGetQuote() {
    setLoading(true);
    setError(null);
    try {
      const res = await cartApi.createQuote(items);
      setQuoteResult(res.data);
      setLinePricing(res.data.line_pricing || []);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to create quote');
    }
    setLoading(false);
  }

  async function handlePlaceOrder() {
    if (!bcQuoteId) return;
    setOrdering(true);
    setError(null);
    try {
      const res = await cartApi.placeOrder(bcQuoteId);
      setOrderResult(res.data);
      clearCart();
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to place order');
    }
    setOrdering(false);
  }

  // Order placed success
  if (orderResult) {
    return (
      <div className="max-w-4xl mx-auto p-4">
        <div className="bg-green-50 border border-green-200 rounded-lg p-8 text-center">
          <svg className="mx-auto h-12 w-12 text-green-500 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <h2 className="text-xl font-bold text-green-800 mb-2">Order Placed!</h2>
          <p className="text-green-700 mb-1">Order Number: <span className="font-mono font-bold">{orderResult.bc_order_number}</span></p>
          {orderResult.total_amount && (
            <p className="text-green-700 mb-4">Total: ${orderResult.total_amount.toFixed(2)}</p>
          )}
          <div className="flex justify-center gap-3 mt-4">
            <Link to="/orders" className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
              View My Orders
            </Link>
            <Link to="/catalog" className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">
              Continue Shopping
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Empty cart
  if (items.length === 0) {
    return (
      <div className="max-w-4xl mx-auto p-4">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Parts Cart</h1>
        <div className="bg-white rounded-lg border p-8 text-center">
          <svg className="mx-auto h-12 w-12 text-gray-300 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z" />
          </svg>
          <p className="text-gray-500 mb-4">Your cart is empty</p>
          <div className="flex justify-center gap-3">
            <Link to="/catalog" className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
              Browse Catalog
            </Link>
            <Link to="/spring-builder" className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">
              Spring Builder
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Parts Cart</h1>
        <button
          onClick={clearCart}
          className="text-sm text-red-600 hover:text-red-800"
        >
          Clear Cart
        </button>
      </div>

      {error && (
        <div className="bg-red-50 text-red-800 p-3 rounded-lg">{error}</div>
      )}

      {/* Cart Table */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Item</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase w-24">Qty</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Est. Price</th>
              <th className="px-4 py-3 w-10"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {items.map(item => (
              <tr key={item.item_number} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm font-mono font-medium text-gray-900">{item.item_number}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{item.description}</td>
                <td className="px-4 py-3 text-center">
                  <input
                    type="number"
                    min="1"
                    value={item.quantity}
                    onChange={e => updateQuantity(item.item_number, parseInt(e.target.value) || 1)}
                    className="w-16 text-center px-2 py-1 border rounded text-sm"
                  />
                </td>
                <td className="px-4 py-3 text-sm text-right text-gray-600">
                  {item.unit_price_estimate != null ? `$${item.unit_price_estimate.toFixed(2)}` : '-'}
                </td>
                <td className="px-4 py-3 text-center">
                  <button
                    onClick={() => removeItem(item.item_number)}
                    className="text-gray-400 hover:text-red-600"
                    title="Remove"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Quote Action */}
      {!quotePricing && (
        <div>
          {!isBCLinked ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800">
              Your account is not linked to Business Central. Please contact support to link your account before requesting a quote.
            </div>
          ) : (
            <button
              onClick={handleGetQuote}
              disabled={loading}
              className="w-full py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
            >
              {loading ? 'Creating Quote...' : 'Get Quote'}
            </button>
          )}
        </div>
      )}

      {/* Pricing Results */}
      {quotePricing && (
        <div className="space-y-4">
          <div className="bg-white rounded-lg border p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-800">Quote Pricing</h2>
              <span className="text-sm text-gray-500 font-mono">Quote #{bcQuoteNumber}</span>
            </div>

            {/* Line pricing */}
            {linePricing && linePricing.length > 0 && (
              <table className="min-w-full divide-y divide-gray-200 mb-4">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Item</th>
                    <th className="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase">Qty</th>
                    <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Unit Price</th>
                    <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Line Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {linePricing.map((line, idx) => (
                    <tr key={idx}>
                      <td className="px-4 py-2 text-sm font-mono">{line.item_number}</td>
                      <td className="px-4 py-2 text-sm text-center">{line.quantity}</td>
                      <td className="px-4 py-2 text-sm text-right">${line.unit_price?.toFixed(2) || '-'}</td>
                      <td className="px-4 py-2 text-sm text-right font-medium">${line.line_total?.toFixed(2) || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* Totals */}
            <div className="border-t pt-4 space-y-1 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Subtotal</span>
                <span className="font-medium">${quotePricing.subtotal?.toFixed(2)}</span>
              </div>
              {quotePricing.tax > 0 && (
                <div className="flex justify-between">
                  <span className="text-gray-600">Tax</span>
                  <span className="font-medium">${quotePricing.tax?.toFixed(2)}</span>
                </div>
              )}
              <div className="flex justify-between text-base font-bold pt-2 border-t">
                <span>Total</span>
                <span>${quotePricing.total?.toFixed(2)}</span>
              </div>
            </div>
          </div>

          {/* Place Order */}
          <button
            onClick={handlePlaceOrder}
            disabled={ordering}
            className="w-full py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 font-medium"
          >
            {ordering ? 'Placing Order...' : 'Place Order'}
          </button>
        </div>
      )}
    </div>
  );
}
