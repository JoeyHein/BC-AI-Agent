/** Effective permissions come from /api/auth/me. The nav does not look at the role name. */

export function can(user, key) {
  return Boolean(user?.permissions?.[key])
}

export function canAny(user, keys) {
  return (keys || []).some((key) => can(user, key))
}

const NAV = {
  '/quotes': 'quotes.view',
  '/orders': 'sales_orders.view',
  '/customers': 'customers.view',
  '/leads': 'quotes.view',
  '/reviews': 'quotes.view',
  '/door-configurator': ['configurator.use', 'quotes.edit'],
  '/production': 'production.view',
  '/cut-work-orders': 'production.view',
  '/install-referrals': 'customers.view',
  '/purchasing': 'purchase_orders.view',
  '/analytics': ['quotes.view', 'sales_orders.view'],
  '/analytics/quoting': 'quotes.view',
  '/analytics/order-age': 'sales_orders.view',
  '/business': ['users.manage', 'quotes.edit', 'sales_orders.edit', 'purchase_orders.view', 'sales_orders.view'],
  '/weekly-email': 'users.manage',
}

export const SETTINGS_NAV_KEYS = [
  'settings.view',
  'pricing.edit',
  'users.view',
  'inventory.view',
  'purchase_orders.view',
]

export function navAllowed(user, path) {
  if (path === '/' || path === '/settings') return true
  const rule = NAV[path]
  if (!rule) return true
  if (Array.isArray(rule)) return canAny(user, rule)
  return can(user, rule)
}

export function showSettings(user) {
  return canAny(user, SETTINGS_NAV_KEYS)
}

/** Company dashboard and the chat tools. Selling prices in the configurator do not open these. */
export const OPERATIONS_NAV_KEYS = [
  'quotes.view',
  'sales_orders.view',
  'purchase_orders.view',
  'inventory.view',
  'production.view',
  'customers.view',
]

export function showDashboard(user) {
  return canAny(user, ['quotes.view', 'sales_orders.view', 'purchase_orders.view', 'inventory.view'])
}

export function showChat(user) {
  return canAny(user, OPERATIONS_NAV_KEYS)
}
