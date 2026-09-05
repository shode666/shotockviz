import api from '@/services/api';

export interface UserSettings {
    telegram_chat_id: string | null;
}

const authService = {
    getSettings: () => api.get<UserSettings>('/auth/settings'),
    updateSettings: (body: UserSettings) => api.patch<UserSettings>('/auth/settings', body),
};

export { authService };
export default authService;
