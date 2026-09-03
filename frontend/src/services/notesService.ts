import api from './api';

const notesService = {
    get: (symbol: string) => api.get(`/notes/${symbol}`),
    upsert: (symbol: string, content: string) => api.put(`/notes/${symbol}`, { content }),
    delete: (symbol: string) => api.delete(`/notes/${symbol}`),
};

export { notesService };
export default notesService;
