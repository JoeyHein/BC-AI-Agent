import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const customerApiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add request interceptor to include customer auth token
customerApiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('customerAuthToken');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Customer Auth API
export const customerAuthApi = {
  // Login
  login: (email, password) =>
    customerApiClient.post('/api/customer/login', { email, password }),

  // Register
  register: (data) =>
    customerApiClient.post('/api/customer/register', data),

  // Verify email
  verifyEmail: (token) =>
    customerApiClient.get(`/api/customer/verify-email/${token}`),

  // Forgot password
  forgotPassword: (email) =>
    customerApiClient.post('/api/customer/forgot-password', { email }),

  // Reset password
  resetPassword: (token, newPassword) =>
    customerApiClient.post('/api/customer/reset-password', {
      token,
      new_password: newPassword
    }),

  // Get current user
  getMe: () =>
    customerApiClient.get('/api/customer/me'),

  // Update profile
  updateProfile: (data) =>
    customerApiClient.patch('/api/customer/me', data),

  // Change password
  changePassword: (oldPassword, newPassword) =>
    customerApiClient.post('/api/customer/change-password', null, {
      params: { old_password: oldPassword, new_password: newPassword }
    }),
};

// Saved Quotes API
export const savedQuotesApi = {
  // List all saved quotes
  getAll: () =>
    customerApiClient.get('/api/customer/portal/saved-quotes'),

  // Get single saved quote
  get: (id) =>
    customerApiClient.get(`/api/customer/portal/saved-quotes/${id}`),

  // Create new saved quote
  create: (data) =>
    customerApiClient.post('/api/customer/portal/saved-quotes', data),

  // Update saved quote
  update: (id, data) =>
    customerApiClient.put(`/api/customer/portal/saved-quotes/${id}`, data),

  // Delete saved quote
  delete: (id) =>
    customerApiClient.delete(`/api/customer/portal/saved-quotes/${id}`),

  // Submit saved quote to BC
  submit: (id) =>
    customerApiClient.post(`/api/customer/portal/saved-quotes/${id}/submit`),

  // Get pricing for a saved quote (creates real BC quote with item lines)
  getPricing: (id) =>
    customerApiClient.post(`/api/customer/portal/saved-quotes/${id}/get-pricing`),

  // Confirm a priced quote (marks as submitted)
  confirm: (id) =>
    customerApiClient.post(`/api/customer/portal/saved-quotes/${id}/confirm`),

  // Refresh pricing after config changes
  refreshPricing: (id) =>
    customerApiClient.post(`/api/customer/portal/saved-quotes/${id}/refresh-pricing`),
};

// BC Quotes API (Customer's BC quotes)
export const bcQuotesApi = {
  // List all BC quotes for customer
  getAll: () =>
    customerApiClient.get('/api/customer/portal/bc-quotes'),

  // Get BC quote details
  get: (quoteId) =>
    customerApiClient.get(`/api/customer/portal/bc-quotes/${quoteId}`),
};

// Orders API
export const ordersApi = {
  // List all orders
  getAll: () =>
    customerApiClient.get('/api/customer/portal/orders'),

  // Get order details with shipments and invoices
  get: (orderId) =>
    customerApiClient.get(`/api/customer/portal/orders/${orderId}`),

  // Get order tracking timeline
  getTracking: (orderId) =>
    customerApiClient.get(`/api/customer/portal/orders/${orderId}/tracking`),
};

// Customer History API
export const historyApi = {
  // Get customer history summary
  get: () =>
    customerApiClient.get('/api/customer/portal/history'),
};

// Re-export door config API for use in customer portal quote builder
// This uses the same endpoints but with customer auth
export const customerDoorConfigApi = {
  // Get full configuration options
  getFullConfig: () =>
    customerApiClient.get('/api/door-config/full-config'),

  // Validate configuration
  validateConfig: (config) =>
    customerApiClient.post('/api/door-config/validate', config),

  // Calculate panels
  calculatePanels: (doorHeight) =>
    customerApiClient.post('/api/door-config/calculate-panels', null, {
      params: { door_height: doorHeight }
    }),

  // Calculate struts
  calculateStruts: (doorWidth, doorHeight, window = 'no') =>
    customerApiClient.post('/api/door-config/calculate-struts', null, {
      params: { door_width: doorWidth, door_height: doorHeight, window }
    }),

  // Get part numbers for a single door configuration
  getPartNumbers: (config) =>
    customerApiClient.post('/api/door-config/get-part-numbers', config),

  // Calculate complete door specifications
  calculateDoor: (config) =>
    customerApiClient.post('/api/door-config/calculate-door', config),

  // Get lift type options
  getLiftTypes: () =>
    customerApiClient.get('/api/door-config/lift-types'),

  // Get spring cycle options
  getSpringCycles: () =>
    customerApiClient.get('/api/door-config/spring-cycles'),

  // Get drum models
  getDrumModels: () =>
    customerApiClient.get('/api/door-config/drum-models'),
};

// Combined customer API export
export const customerApi = {
  auth: customerAuthApi,
  savedQuotes: savedQuotesApi,
  bcQuotes: bcQuotesApi,
  orders: ordersApi,
  history: historyApi,
  doorConfig: customerDoorConfigApi,
};

export default customerApiClient;
