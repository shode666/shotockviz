import { createFileRoute } from '@tanstack/react-router'
import AlertsPage from '@/components/pages/AlertsPage'

export const Route = createFileRoute('/alerts')({
    component: AlertsPage,
})
