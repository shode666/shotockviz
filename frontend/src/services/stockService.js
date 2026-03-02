import api from '@/services/api';

const stockService = {
    search: (query) => api.get('/stocks/search', { params: { q: query } }),
    /** Batch name lookup: returns { [symbol]: companyName } */
    getNames: (symbols) =>
        api.get('/stocks/names', { params: { symbols: symbols.join(',') } }),
    getQuote: async (symbol) => {
        const res = await api.get(`/stocks/${symbol}/quote`);
        // 202 = cache miss, background fetch triggered — treat as "no data yet"
        if (res.status === 202) return { data: null };
        return res;
    },
    getHistory: (symbol, tf = '1D') =>
        api.get(`/stocks/${symbol}/history`, { params: { tf }, timeout: 30_000 }),
    getFundamentals: (symbol) => api.get(`/stocks/${symbol}/fundamentals`),
    getNews: (symbol) => api.get(`/stocks/${symbol}/news`),
    screener: (params) => api.get('/screener', { params }),
};

export default stockService;
