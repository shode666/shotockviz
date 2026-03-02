import { createFileRoute } from '@tanstack/react-router'
import ChartPage from '@/components/pages/ChartPage'

export const Route = createFileRoute('/')({
  component: ChartPage,
})
