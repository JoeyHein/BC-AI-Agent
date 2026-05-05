function PricingSettings() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-medium text-gray-900">Pricing</h2>
        <p className="text-sm text-gray-500">
          Pricing is managed in Business Central. The portal looks up unit
          prices from BC's published Sales Price Lists per customer.
        </p>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h3 className="text-sm font-medium text-blue-800">How quote pricing is resolved</h3>
        <ol className="mt-2 list-decimal list-inside space-y-1 text-sm text-blue-700">
          <li>
            <span className="font-medium">Customer-group price</span> —
            <code className="mx-1">SalesPriceLists</code> filtered by{' '}
            <code>Product_No</code> + the customer's{' '}
            <code>Customer_Price_Group</code> + the item's UoM.
          </li>
          <li>
            <span className="font-medium">Default list price</span> — same
            entity, no group filter, returns the all-customer list price.
          </li>
          <li>
            <span className="font-medium">Item card price</span> —{' '}
            <code>ItemMasterList.Unit_Price</code> as a final fallback.
          </li>
        </ol>
        <p className="mt-3 text-sm text-blue-700">
          To adjust pricing for a tier or part, edit the BC{' '}
          <strong>Customer Price Group</strong> entries (<code>PLAT</code>,{' '}
          <code>GOLD</code>, <code>SILV</code>, <code>BRON</code>,{' '}
          <code>UNLI</code>, <code>OPIN</code>) and their corresponding{' '}
          <strong>Sales Price List</strong> headers (<code>PLAT-01</code>,{' '}
          <code>GOLD-01</code>, etc., plus <code>ALL CUSTOMERS</code> for
          the default list price).
        </p>
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
        There is no app-side margin override. Cost adjustments, tier-margin
        matrices, and prefix overrides have been retired — BC is the single
        source of truth. Customer assignments sync from BC every 30 minutes.
      </div>
    </div>
  )
}

export default PricingSettings
