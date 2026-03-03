import api from '@/services/api';

const alertService = {
    getAll: () => api.get('/alerts'),
    create: (body) => api.post('/alerts', body),
    delete: (id) => api.delete(`/alerts/${id}`),
    toggle: (id) => api.patch(`/alerts/${id}/toggle`),
};

export { alertService };
export default alertService;
