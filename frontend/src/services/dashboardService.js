import api from './api';

const dashboardService = {
    getOverview: () => api.get('/dashboard'),
};

export default dashboardService;
