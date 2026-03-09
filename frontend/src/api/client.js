import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add request interceptor to include auth token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('authToken');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Quotes API
export const quotesApi = {
  // Get pending reviews
  getPendingReviews: (params = {}) =>
    apiClient.get('/api/quotes/pending-review', { params }),

  // Get all quotes (including approved, rejected, etc.)
  getAllQuotes: (params = {}) =>
    apiClient.get('/api/quotes/pending-review', { params: { ...params, status: 'all' } }),

  // Get specific quote
  getQuote: (quoteId) =>
    apiClient.get(`/api/quotes/${quoteId}`),

  // Approve quote
  approveQuote: (quoteId, { notes = '', bc_customer_id = null, create_in_bc = false } = {}) =>
    apiClient.post(`/api/quotes/${quoteId}/approve`, {
      notes,
      bc_customer_id,
      create_in_bc
    }),

  // Reject quote
  rejectQuote: (quoteId, reason) =>
    apiClient.post(`/api/quotes/${quoteId}/reject`, { reason }),

  // Create quote in Business Central
  createBCQuote: (quoteRequestId) =>
    apiClient.post('/api/quotes/create-bc-quote', {
      quote_request_id: quoteRequestId
    }),

  // Get quote statistics
  getQuoteStats: () =>
    apiClient.get('/api/quotes/stats/summary'),

  // Get learning progress stats
  getLearningProgress: () =>
    apiClient.get('/api/quotes/stats/learning-progress'),
};

// Analytics API
export const analyticsApi = {
  // Dashboard summary
  getDashboardSummary: () =>
    apiClient.get('/api/analytics/dashboard/summary'),

  // Item frequency analysis
  getItemFrequency: () =>
    apiClient.get('/api/analytics/items/frequency'),

  // Item affinity (frequently bought together)
  getItemAffinity: (minSupport = 2) =>
    apiClient.get('/api/analytics/items/affinity', { params: { min_support: minSupport } }),

  // Customer preferences
  getCustomerPreferences: () =>
    apiClient.get('/api/analytics/customers/preferences'),

  // Customer recommendations
  getCustomerRecommendations: (customerNumber) =>
    apiClient.get(`/api/analytics/customers/${customerNumber}/recommendations`),

  // Pricing trends
  getPricingTrends: () =>
    apiClient.get('/api/analytics/pricing/trends'),

  // Demand forecast
  getDemandForecast: (lookbackDays = 90) =>
    apiClient.get('/api/analytics/demand/forecast', { params: { lookback_days: lookbackDays } }),

  // Full report
  getFullReport: () =>
    apiClient.get('/api/analytics/report/full'),
};

// Email Feedback API (for categorization learning)
export const emailFeedbackApi = {
  // Mark email as not a quote request
  markAsNotQuote: (emailId) =>
    apiClient.post(`/api/email-feedback/${emailId}/mark-not-quote`),

  // Provide specific category feedback
  provideFeedback: (emailId, correctCategory, comment = null) =>
    apiClient.post(`/api/email-feedback/${emailId}`, {
      correct_category: correctCategory,
      comment
    }),

  // Get categorization statistics
  getCategorizationStats: () =>
    apiClient.get('/api/email-feedback/stats'),
};

// Door Configurator API
export const doorConfigApi = {
  // Get full configuration options
  getFullConfig: () =>
    apiClient.get('/api/door-config/full-config'),

  // Get door types
  getDoorTypes: () =>
    apiClient.get('/api/door-config/types'),

  // Get door series for a type
  getDoorSeries: (doorType) =>
    apiClient.get(`/api/door-config/series/${doorType}`),

  // Get colors for a series
  getColors: (seriesId) =>
    apiClient.get(`/api/door-config/colors/${seriesId}`),

  // Get panel designs for a series
  getPanelDesigns: (seriesId) =>
    apiClient.get(`/api/door-config/panel-designs/${seriesId}`),

  // Get window inserts
  getWindowInserts: () =>
    apiClient.get('/api/door-config/window-inserts'),

  // Get glazing options
  getGlazingOptions: (doorType) =>
    apiClient.get(`/api/door-config/glazing-options/${doorType}`),

  // Get track options
  getTrackOptions: () =>
    apiClient.get('/api/door-config/track-options'),

  // Get hardware options
  getHardwareOptions: () =>
    apiClient.get('/api/door-config/hardware-options'),

  // Get operator options
  getOperatorOptions: (doorType) =>
    apiClient.get(`/api/door-config/operator-options/${doorType}`),

  // Get dimension constraints
  getDimensionConstraints: (seriesId) =>
    apiClient.get(`/api/door-config/dimension-constraints/${seriesId}`),

  // Validate configuration
  validateConfig: (config) =>
    apiClient.post('/api/door-config/validate', config),

  // Calculate panels
  calculatePanels: (doorHeight) =>
    apiClient.post('/api/door-config/calculate-panels', null, { params: { door_height: doorHeight } }),

  // Calculate struts
  calculateStruts: (doorWidth, doorHeight, window = 'no') =>
    apiClient.post('/api/door-config/calculate-struts', null, {
      params: { door_width: doorWidth, door_height: doorHeight, window }
    }),

  // Generate quote
  generateQuote: (request) =>
    apiClient.post('/api/door-config/generate-quote', request),

  // Get part numbers for a single door configuration
  getPartNumbers: (config) =>
    apiClient.post('/api/door-config/get-part-numbers', config),

  // Get part numbers for entire quote (multiple doors)
  getPartsForQuote: (request) =>
    apiClient.post('/api/door-config/get-parts-for-quote', request),

  // Calculate complete door specifications (weight, springs, drums, etc.)
  calculateDoor: (config) =>
    apiClient.post('/api/door-config/calculate-door', config),

  // Get lift type options
  getLiftTypes: () =>
    apiClient.get('/api/door-config/lift-types'),

  // Get spring cycle options
  getSpringCycles: () =>
    apiClient.get('/api/door-config/spring-cycles'),

  // Get drum models
  getDrumModels: () =>
    apiClient.get('/api/door-config/drum-models'),

  // Get commercial window types
  getWindowTypes: () =>
    apiClient.get('/api/door-config/window-types'),

  // Calculate springs only
  calculateSpring: (doorWeight, doorHeight, drumModel = 'D525-216', targetCycles = 10000) =>
    apiClient.post('/api/door-config/calculate-spring', null, {
      params: { door_weight: doorWeight, door_height: doorHeight, drum_model: drumModel, target_cycles: targetCycles }
    }),
};

// Production API
export const productionApi = {
  // Get production API status
  getStatus: () =>
    apiClient.get('/production/status'),

  // Get work centers from BC
  getWorkCenters: (limit = 100) =>
    apiClient.get('/production/work-centers', { params: { limit } }),

  // Get production orders
  getOrders: (params = {}) =>
    apiClient.get('/production/orders', { params }),

  // Get production order components
  getOrderComponents: (orderNo) =>
    apiClient.get(`/production/orders/${orderNo}/components`),

  // Get all components
  getComponents: (params = {}) =>
    apiClient.get('/production/components', { params }),

  // Get specific production order
  getOrder: (orderNo) =>
    apiClient.get(`/production/orders/${orderNo}`),

  // Create production order
  createOrder: (data) =>
    apiClient.post('/production/orders', data),

  // Release production order
  releaseOrder: (orderNo) =>
    apiClient.post(`/production/orders/${orderNo}/release`),

  // Finish production order
  finishOrder: (orderNo) =>
    apiClient.post(`/production/orders/${orderNo}/finish`),

  // Calculate production schedule
  calculateSchedule: (data) =>
    apiClient.post('/production/schedule/calculate', data),

  // Get work center capacity
  getCapacity: (dateFrom, dateTo, workCenter = null) =>
    apiClient.get('/production/schedule/capacity', {
      params: { dateFrom, dateTo, workCenter }
    }),

  // Get lead times
  getLeadTimes: () =>
    apiClient.get('/production/schedule/lead-times'),

  // ==================== Task Completion API ====================

  // Get tasks by date (for shop floor view)
  getTasksByDate: (date, includeMaterials = true) =>
    apiClient.get(`/production/tasks/by-date/${date}`, {
      params: { include_materials: includeMaterials }
    }),

  // Get tasks for a specific production order
  getTasksByOrder: (productionOrderId) =>
    apiClient.get(`/production/tasks/order/${productionOrderId}`),

  // Mark a task as complete
  completeTask: (taskId, userId = null, quantityCompleted = null) =>
    apiClient.post('/production/tasks/complete', {
      taskId,
      userId,
      quantityCompleted
    }),

  // Mark a line item as picked (for pick/pack orders)
  pickLineItem: (lineItemId, quantityPicked = null, userId = null) =>
    apiClient.post('/production/tasks/pick-item', {
      lineItemId,
      quantityPicked,
      userId
    }),

  // Unmark a line item as picked (reset pick status)
  unpickLineItem: (lineItemId, userId = null) =>
    apiClient.post('/production/tasks/unpick-item', {
      lineItemId,
      userId
    }),

  // Ship a completed order (supports both production orders and pick/pack sales orders)
  shipOrder: (salesOrderId, userId = null) =>
    apiClient.post(`/production/tasks/sales-order/${salesOrderId}/ship`, {
      userId
    }),

  // Get order components with material availability
  getComponentsWithAvailability: (productionOrderId, orderNo) =>
    apiClient.get(`/production/tasks/order/${productionOrderId}/components`, {
      params: { order_no: orderNo }
    }),

  // Get daily summary for dashboard
  getDailySummary: (date) =>
    apiClient.get(`/production/tasks/summary/${date}`),

  // ==================== Scheduling API ====================

  // Get all open sales orders with work orders for the side panel
  // If onlyUnscheduled=true (default), filters to only orders with unscheduled tasks
  getOpenOrders: (onlyUnscheduled = true) =>
    apiClient.get('/production/tasks/open-orders', {
      params: { only_unscheduled: onlyUnscheduled }
    }),

  // Get unscheduled orders for the side panel (legacy)
  getUnscheduledOrders: () =>
    apiClient.get('/production/tasks/unscheduled'),

  // Get all sales orders scheduled for a specific date
  // Used to show SO numbers on calendar dates
  getScheduledByDate: (date) =>
    apiClient.get(`/production/tasks/scheduled-by-date/${date}`),

  // Get all scheduled sales orders grouped by date for a date range
  // Efficient endpoint for calendar display
  getScheduledSummary: (dateFrom, dateTo) =>
    apiClient.get('/production/tasks/scheduled-summary', {
      params: { date_from: dateFrom, date_to: dateTo }
    }),

  // Schedule a sales order to a specific date (drag & drop)
  scheduleOrder: (salesOrderId, scheduledDate) =>
    apiClient.post('/production/tasks/schedule', {
      salesOrderId,
      scheduledDate
    }),

  // Schedule a single production order (for orphan orders)
  scheduleProductionOrder: (productionOrderId, scheduledDate) =>
    apiClient.post('/production/tasks/schedule-production-order', null, {
      params: { productionOrderId, scheduledDate }
    }),

  // Remove an order from the schedule
  unscheduleOrder: (salesOrderId) =>
    apiClient.delete(`/production/tasks/unschedule/${salesOrderId}`),

  // Unschedule ALL orders (clear entire schedule)
  unscheduleAll: () =>
    apiClient.delete('/production/tasks/unschedule-all'),

  // ==================== Work Order Linking API ====================

  // Link a work order to a sales order
  linkWorkOrder: (workOrderId, salesOrderId) =>
    apiClient.post('/production/tasks/link-work-order', {
      workOrderId,
      salesOrderId
    }),

  // Unlink a work order from its sales order
  unlinkWorkOrder: (workOrderId) =>
    apiClient.post(`/production/tasks/unlink-work-order/${workOrderId}`),
};

// Inventory API
export const inventoryApi = {
  // Check availability for items
  checkAvailability: (items, requiredDate = null) =>
    apiClient.post('/inventory/check-availability', { items, requiredDate }),

  // Get inventory levels
  getLevels: (params = {}) =>
    apiClient.get('/inventory/levels', { params }),

  // Get specific item inventory
  getItem: (itemNumber) =>
    apiClient.get(`/inventory/item/${itemNumber}`),

  // Get item movements
  getItemMovements: (itemNumber, days = 30) =>
    apiClient.get(`/inventory/item/${itemNumber}/movements`, { params: { days } }),

  // Get item categories
  getCategories: () =>
    apiClient.get('/inventory/categories'),

  // Get locations
  getLocations: () =>
    apiClient.get('/inventory/locations'),
};

// Orders API (Admin)
export const ordersApi = {
  // Get all orders
  getAll: (params = {}) =>
    apiClient.get('/api/orders', { params }),

  // Get specific order
  getOrder: (orderId) =>
    apiClient.get(`/api/orders/${orderId}`),

  // Update order status
  updateStatus: (orderId, status, notes = '') =>
    apiClient.patch(`/api/orders/${orderId}/status`, { status, notes }),

  // Get order timeline
  getTimeline: (orderId) =>
    apiClient.get(`/api/orders/${orderId}/timeline`),

  // Convert quote to order
  convertQuote: (quoteId) =>
    apiClient.post('/api/orders/convert-quote', { quote_id: quoteId }),

  // Create shipment for order
  createShipment: (orderId, shipmentData) =>
    apiClient.post(`/api/orders/${orderId}/ship`, shipmentData),

  // Create invoice for order
  createInvoice: (orderId) =>
    apiClient.post(`/api/orders/${orderId}/invoice`),
};

// AI Chat API
export const chatApi = {
  // Send a message to the AI agent
  sendMessage: (message, context = {}, conversationId = null) =>
    apiClient.post('/api/chat/message', {
      message,
      context,
      conversation_id: conversationId
    }),

  // Get list of conversations
  getConversations: (limit = 20) =>
    apiClient.get('/api/chat/conversations', { params: { limit } }),

  // Get conversation history
  getConversation: (conversationId) =>
    apiClient.get(`/api/chat/conversations/${conversationId}`),

  // Delete a conversation
  deleteConversation: (conversationId) =>
    apiClient.delete(`/api/chat/conversations/${conversationId}`),

  // Clear a conversation (keep it but remove messages)
  clearConversation: (conversationId) =>
    apiClient.post(`/api/chat/conversations/${conversationId}/clear`),
};

// Settings API
export const settingsApi = {
  // Get a specific setting by key
  getSetting: (key) =>
    apiClient.get(`/api/settings/${key}`),

  // Update a setting
  updateSetting: (key, value, description = null) =>
    apiClient.put(`/api/settings/${key}`, { value, description }),

  // Spring Inventory endpoints
  getSpringInventory: () =>
    apiClient.get('/api/settings/spring-inventory/current'),

  getAvailableSpringSizes: () =>
    apiClient.get('/api/settings/spring-inventory/available-sizes'),

  getAvailableCoils: () =>
    apiClient.get('/api/settings/spring-inventory/coils'),

  getWireSizesForCoil: (coilId) =>
    apiClient.get(`/api/settings/spring-inventory/coils/${coilId}/wire-sizes`),

  updateSpringInventory: (inventory) =>
    apiClient.put('/api/settings/spring-inventory', { inventory }),

  getSpringInventorySummary: () =>
    apiClient.get('/api/settings/spring-inventory/summary'),

  // Pricing Tier endpoints
  getPricingTiers: () =>
    apiClient.get('/api/settings/pricing-tiers/current'),

  updatePricingTiers: (margins) =>
    apiClient.put('/api/settings/pricing-tiers', { margins }),

  getPricingCostAdjustments: () =>
    apiClient.get('/api/settings/pricing-cost-adjustments/current'),

  updatePricingCostAdjustments: (adjustments) =>
    apiClient.put('/api/settings/pricing-cost-adjustments', { adjustments }),

  getPricingCategories: () =>
    apiClient.get('/api/settings/pricing-categories'),

  // Part-number prefix margin overrides
  getPrefixMargins: () =>
    apiClient.get('/api/settings/pricing-prefix-margins/current'),

  updatePrefixMargins: (overrides) =>
    apiClient.put('/api/settings/pricing-prefix-margins', { overrides }),

  // BC Group → Tier mapping
  getBCGroupMapping: () =>
    apiClient.get('/api/settings/bc-group-mapping/current'),

  updateBCGroupMapping: (mapping) =>
    apiClient.put('/api/settings/bc-group-mapping', { mapping }),

  getBCPriceGroups: () =>
    apiClient.get('/api/settings/bc-group-mapping/bc-groups'),
};

// Quote Review API (admin)
export const quoteReviewApi = {
  getSnapshots: (params = {}) =>
    apiClient.get('/api/admin/quote-review/snapshots', { params }),

  reviewQuote: (bcQuoteId, data = {}) =>
    apiClient.post(`/api/admin/quote-review/${bcQuoteId}/review`, data),

  analyzePatterns: (limit = 20) =>
    apiClient.post('/api/admin/quote-review/analyze-patterns', { limit }),

  getReviews: (params = {}) =>
    apiClient.get('/api/admin/quote-review/reviews', { params }),

  getReview: (reviewId) =>
    apiClient.get(`/api/admin/quote-review/reviews/${reviewId}`),
};

// Customers API (admin)
export const customersApi = {
  updatePricingTier: (customerId, pricingTier) =>
    apiClient.patch(`/api/admin/customers/${customerId}/pricing-tier`, {
      pricing_tier: pricingTier,
    }),
};

// Catalog Builder API (Admin)
export const catalogApi = {
  runPipeline: () => apiClient.post('/api/admin/catalog/run-pipeline'),
  getStaging: (params = {}) => apiClient.get('/api/admin/catalog/staging', { params }),
  getReviewQueue: (params = {}) => apiClient.get('/api/admin/catalog/review-queue', { params }),
  resolveReview: (reviewId, data) => apiClient.post(`/api/admin/catalog/review/${reviewId}`, data),
  getDuplicates: (params = {}) => apiClient.get('/api/admin/catalog/duplicates', { params }),
  getParts: (params = {}) => apiClient.get('/api/admin/catalog/parts', { params }),
  getStats: () => apiClient.get('/api/admin/catalog/stats'),
  getSpecialOrders: (params = {}) => apiClient.get('/api/admin/catalog/special-orders', { params }),
  updateSpecialOrder: (orderId, data) => apiClient.patch(`/api/admin/catalog/special-orders/${orderId}`, data),
  updatePartStatus: (partId, catalogStatus) => apiClient.patch(`/api/admin/catalog/parts/${partId}/status`, { catalog_status: catalogStatus }),
  bulkActivateParts: (data) => apiClient.post('/api/admin/catalog/parts/activate', data),
  getVisibility: () => apiClient.get('/api/admin/catalog/visibility'),
  setVisibility: (visible) => apiClient.post('/api/admin/catalog/visibility', { visible }),
};

// Inventory Agent API (Admin)
export const inventoryAgentApi = {
  runReview: () => apiClient.post('/api/admin/inventory-agent/run'),
  getSignals: (params = {}) => apiClient.get('/api/admin/inventory-agent/signals', { params }),
  getDashboard: () => apiClient.get('/api/admin/inventory-agent/dashboard'),
  acknowledgeSignal: (signalId) => apiClient.post(`/api/admin/inventory-agent/signals/${signalId}/ack`),
};

// PO Agent API (Admin)
export const poAgentApi = {
  runGeneration: () => apiClient.post('/api/admin/po-agent/run'),
  getDrafts: (params = {}) => apiClient.get('/api/admin/po-agent/drafts', { params }),
  approveDraft: (draftId) => apiClient.post(`/api/admin/po-agent/drafts/${draftId}/approve`),
  rejectDraft: (draftId, data) => apiClient.post(`/api/admin/po-agent/drafts/${draftId}/reject`, data),
  getStats: () => apiClient.get('/api/admin/po-agent/stats'),
};

export default apiClient;
