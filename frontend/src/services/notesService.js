import api from './api';

const notesService = {
    get: (symbol) => api.get(`/notes/${symbol}`),
    upsert: (symbol, content) => api.put(`/notes/${symbol}`, { content }),
    delete: (symbol) => api.delete(`/notes/${symbol}`),
};

export default notesService;
