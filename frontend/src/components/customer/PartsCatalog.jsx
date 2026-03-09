import { useState, useEffect } from 'react';
import { catalogApi } from '../../api/customerClient';

const CATEGORIES = [
  { value: '', label: 'All Categories' },
  { value: 'spring', label: 'Springs' },
  { value: 'panel', label: 'Panels' },
  { value: 'track', label: 'Tracks' },
  { value: 'hardware', label: 'Hardware' },
  { value: 'hardware_kit', label: 'Hardware Kits' },
  { value: 'shaft', label: 'Shafts' },
  { value: 'plastic', label: 'Weather Stripping' },
  { value: 'glazing_kit', label: 'Glazing Kits' },
];

export default function PartsCatalog() {
  const [parts, setParts] = useState([]);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [loading, setLoading] = useState(false);
  const [pricingTier, setPricingTier] = useState(null);
  const [catalogHidden, setCatalogHidden] = useState(false);

  useEffect(() => { loadParts(); }, [category]);

  async function loadParts() {
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (category) params.category = category;
      const res = await catalogApi.browse(params);
      if (res.data.catalog_hidden) {
        setCatalogHidden(true);
        setParts([]);
      } else {
        setCatalogHidden(false);
        setParts(res.data.items || []);
        setPricingTier(res.data.pricing_tier);
      }
    } catch (e) {
      console.error('Failed to load catalog:', e);
    }
    setLoading(false);
  }

  async function handleSearch(e) {
    e.preventDefault();
    if (!search.trim()) {
      loadParts();
      return;
    }
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (category) params.category = category;
      const res = await catalogApi.search(search.trim(), params);
      setParts(res.data.items || []);
    } catch (e) {
      console.error('Search failed:', e);
    }
    setLoading(false);
  }

  return (
    <div className="max-w-6xl mx-auto p-4 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Parts Catalog</h1>
        {pricingTier && (
          <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium capitalize">
            {pricingTier} Tier
          </span>
        )}
      </div>

      {catalogHidden && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-center">
          <p className="text-blue-800">The parts catalog is currently unavailable. Please check back later.</p>
        </div>
      )}

      {/* Search & Filter */}
      <div className="flex flex-col sm:flex-row gap-3">
        <form onSubmit={handleSearch} className="flex-1 flex gap-2">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by part number or description..."
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <button
            type="submit"
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            Search
          </button>
        </form>
        <select
          value={category}
          onChange={e => setCategory(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg"
        >
          {CATEGORIES.map(c => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
      </div>

      {/* Results */}
      {loading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : parts.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          No parts found. {search ? 'Try a different search term.' : 'The catalog may not have active parts yet.'}
        </div>
      ) : (
        <div className="bg-white rounded-lg border overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Part Number</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Price</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {parts.map(part => (
                <tr key={part.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-mono font-medium text-gray-900">{part.item_number}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{part.description}</td>
                  <td className="px-4 py-3 text-sm">
                    <span className="capitalize text-gray-600">{part.category}</span>
                    {part.subcategory && <span className="text-gray-400 ml-1">/ {part.subcategory}</span>}
                  </td>
                  <td className="px-4 py-3 text-sm text-right text-gray-900">
                    {part.retail_price != null ? `$${part.retail_price.toFixed(2)}` : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-gray-400">{parts.length} results</p>
    </div>
  );
}
