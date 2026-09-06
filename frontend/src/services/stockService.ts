import api from '@/services/api';

const stockService = {
    search: (query: string) => api.get('/stocks/search', { params: { q: query } }),
    /** Batch name lookup: returns { [symbol]: companyName } */
    getNames: (symbols: string[]) =>
        api.get('/stocks/names', { params: { symbols: symbols.join(',') } }),
    /** Batch quote fetch: returns { [symbol]: quoteObj | null } for all symbols in one request */
    getQuotesBatch: (symbols: string[]) =>
        api.get('/stocks/quotes', { params: { symbols: symbols.join(',') }, timeout: 15_000 }),
    getQuote: async (symbol: string) => {
        try {
            return await api.get(`/stocks/${symbol}/quote`, { timeout: 10_000 });
        } catch (err: any) {
            // Axios throws on 4xx — catch 404 (symbol not found) and return null
            // so callers can distinguish "not found" from real errors (timeout, network)
            if (err?.response?.status === 404) return { data: null };
            throw err;
        }
    },
    getHistory: (symbol: string, tf = '1D') =>
        api.get(`/stocks/${symbol}/history`, { params: { timeframe: tf }, timeout: 30_000 }),
    getFundamentals: (symbol: string) => api.get(`/stocks/${symbol}/fundamentals`),
    getNews: (symbol: string) => api.get(`/stocks/${symbol}/news`),
    screener: (params: Record<string, unknown>) => api.get('/screener', { params }),
    /** bd:features-2026-09 slice 2 — support/resistance price levels for a symbol */
    getSrLevels: (symbol: string) => api.get(`/sr-levels/${symbol}`),
    /** bd:shotockviz-474 — create a user-owned horizontal S/R level. Requires auth
     * (interceptor in api.ts attaches the token automatically when present). */
    createSrLevel: (symbol: string, body: { price: number; level_type: 'support' | 'resistance'; tag?: string }) =>
        api.post(`/sr-levels/${symbol}`, body),
    /** bd:shotockviz-474 — delete a level the caller owns. */
    deleteSrLevel: (id: number) => api.delete(`/sr-levels/${id}`),
};

export { stockService };
export default stockService;
