import { createFileRoute } from '@tanstack/react-router'
import ScreenerPage from '@/components/pages/ScreenerPage'

export const Route = createFileRoute('/screener')({
    component: ScreenerPage,
})
