import api from '@/services/api';

const stockService = {
    search: (query) => api.get('/stocks/search', { params: { q: query } }),
    /** Batch name lookup: returns { [symbol]: companyName } */
    getNames: (symbols) =>
        api.get('/stocks/names', { params: { symbols: symbols.join(',') } }),
    /** Batch quote fetch: returns { [symbol]: quoteObj | null } for all symbols in one request */
    getQuotesBatch: (symbols) =>
        api.get('/stocks/quotes', { params: { symbols: symbols.join(',') }, timeout: 15_000 }),
    getQuote: async (symbol) => {
        try {
            return await api.get(`/stocks/${symbol}/quote`, { timeout: 10_000 });
        } catch (err) {
            // Axios throws on 4xx — catch 404 (symbol not found) and return null
            // so callers can distinguish "not found" from real errors (timeout, network)
            if (err?.response?.status === 404) return { data: null };
            throw err;
        }
    },
    getHistory: (symbol, tf = '1D') =>
        api.get(`/stocks/${symbol}/history`, { params: { timeframe: tf }, timeout: 30_000 }),
    getFundamentals: (symbol) => api.get(`/stocks/${symbol}/fundamentals`),
    getNews: (symbol) => api.get(`/stocks/${symbol}/news`),
    screener: (params) => api.get('/screener', { params }),
};

export { stockService };
export default stockService;
