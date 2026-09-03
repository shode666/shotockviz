import api from '@/services/api';

const watchlistService = {
    // Watchlists
    getAll: () => api.get('/watchlists'),
    create: (name: string) => api.post('/watchlists', { name }),
    delete: (id: number | string) => api.delete(`/watchlists/${id}`),

    // Stocks in watchlist
    addStock: (watchlistId: number | string, symbol: string) =>
        api.post(`/watchlists/${watchlistId}/stocks`, { symbol }),
    removeStock: (watchlistId: number | string, symbol: string) =>
        api.delete(`/watchlists/${watchlistId}/stocks/${symbol}`),
    // symbols: string[] in desired order
    reorderStocks: (watchlistId: number | string, symbols: string[]) => api.patch(
        `/watchlists/${watchlistId}/stocks/reorder`,
        { items: symbols.map((symbol, index) => ({ symbol, sort_order: index })) }
    ),
};

export { watchlistService };
export default watchlistService;
