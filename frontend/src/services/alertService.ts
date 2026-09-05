import api from '@/services/api';

const alertService = {
    getAll: () => api.get('/alerts'),
    create: (body: Record<string, unknown>) => api.post('/alerts', body),
    // bd:shotockviz-d09 — PUT /alerts/{id} (AlertUpdate) only accepts
    // condition/value/channel; symbol and alert_type are not part of that
    // schema (backend/models/schemas.py:274-277) so callers must not send them.
    update: (id: number | string, body: Record<string, unknown>) => api.put(`/alerts/${id}`, body),
    delete: (id: number | string) => api.delete(`/alerts/${id}`),
    toggle: (id: number | string) => api.patch(`/alerts/${id}/toggle`),
};

export { alertService };
export default alertService;
