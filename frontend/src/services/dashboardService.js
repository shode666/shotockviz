import api from './api';

const dashboardService = {
    getOverview: () => api.get('/dashboard', { timeout: 30_000 }),
};

export { dashboardService };
export default dashboardService;
