// Customer-portal feature flags.
//
// CUSTOMER_PARTS_FEATURES_ENABLED gates the parts-ordering experience
// (Catalog, Spring Builder, Cart) that is built but NOT yet ready for
// customers — it still needs a redesign into a user-friendly product.
// While false, those tabs are hidden AND their routes redirect to the
// dashboard so they can't be reached by direct URL. Flip to true to
// re-expose them (they remain dealer-gated where that applied before).
export const CUSTOMER_PARTS_FEATURES_ENABLED = false
