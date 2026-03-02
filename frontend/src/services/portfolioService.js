import api from '@/services/api';

const portfolioService = {
    getTransactions: () => api.get('/portfolio'),
    getAnalytics: () => api.get('/portfolio/analytics'),
    addTransaction: (body) => api.post('/portfolio/transactions', body),
    updateTransaction: (id, body) => api.put(`/portfolio/transactions/${id}`, body),
    deleteTransaction: (id) => api.delete(`/portfolio/transactions/${id}`),
    getPerformance: (period = '6M') => api.get(`/portfolio/performance?period=${period}`),
};

export default portfolioService;
