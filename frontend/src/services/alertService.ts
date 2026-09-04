import api from '@/services/api';

const alertService = {
    getAll: () => api.get('/alerts'),
    create: (body: Record<string, unknown>) => api.post('/alerts', body),
    delete: (id: number | string) => api.delete(`/alerts/${id}`),
    toggle: (id: number | string) => api.patch(`/alerts/${id}/toggle`),
};

export { alertService };
export default alertService;
