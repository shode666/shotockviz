import useAuthStore from '@/store/authStore';

export default function useAuth() {
    const { user, isAuthenticated, isLoading, login, register, logout, checkAuth } =
        useAuthStore();
    return { user, isAuthenticated, isLoading, login, register, logout, checkAuth };
}
