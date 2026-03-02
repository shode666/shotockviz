import { createFileRoute } from '@tanstack/react-router'
import NewsPage from '@/components/pages/NewsPage'

export const Route = createFileRoute('/news')({
    component: NewsPage,
})
