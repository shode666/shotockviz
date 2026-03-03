import api from '@/services/api';

const watchlistService = {
    // Watchlists
    getAll: () => api.get('/watchlists'),
    create: (name) => api.post('/watchlists', { name }),
    delete: (id) => api.delete(`/watchlists/${id}`),

    // Stocks in watchlist
    addStock: (watchlistId, symbol) => api.post(`/watchlists/${watchlistId}/stocks`, { symbol }),
    removeStock: (watchlistId, symbol) => api.delete(`/watchlists/${watchlistId}/stocks/${symbol}`),
    // symbols: string[] in desired order
    reorderStocks: (watchlistId, symbols) => api.patch(
        `/watchlists/${watchlistId}/stocks/reorder`,
        { items: symbols.map((symbol, index) => ({ symbol, sort_order: index })) }
    ),
};

export { watchlistService };
export default watchlistService;
