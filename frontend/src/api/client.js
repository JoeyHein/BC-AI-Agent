import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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

export default apiClient;
