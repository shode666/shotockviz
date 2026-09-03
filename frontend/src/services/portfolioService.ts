import api from '@/services/api';

const portfolioService = {
    getTransactions: () => api.get('/portfolio'),
    getAnalytics: () => api.get('/portfolio/analytics', { timeout: 20_000 }),
    addTransaction: (body: Record<string, unknown>) => api.post('/portfolio/transactions', body),
    updateTransaction: (id: number | string, body: Record<string, unknown>) =>
        api.put(`/portfolio/transactions/${id}`, body),
    deleteTransaction: (id: number | string) => api.delete(`/portfolio/transactions/${id}`),
    getPerformance: (period = '6M') => api.get(`/portfolio/performance?period=${period}`),
};

export { portfolioService };
export default portfolioService;
