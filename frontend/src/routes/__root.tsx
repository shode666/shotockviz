import { useEffect } from 'react'
import { HeadContent, Outlet, Scripts, createRootRoute } from '@tanstack/react-router'
import { Toaster } from 'react-hot-toast'
import { GoogleOAuthProvider, useGoogleOneTapLogin } from '@react-oauth/google'

import Navbar from '@/components/common/Navbar'
import Sidebar from '@/components/common/Sidebar'
import StatusBar from '@/components/common/StatusBar'
import SearchModal from '@/components/modals/SearchModal'
import AIChatPanel from '@/components/common/AIChatPanel'
import ClientOnly from '@/components/common/ClientOnly'
import useAppStore from '@/store/appStore'
import useAuthStore from '@/store/authStore'
import useWebSocket from '@/hooks/useWebSocket'
import useBackendReady from '@/hooks/useBackendReady'

import appCss from '@/styles.css?url'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined

/**
 * Silent Google One Tap re-auth.
 * Activates only when: auth check finished + not authenticated + Google configured.
 * Uses `auto_select` so it silently picks the account without showing a popup
 * when the user is already signed in to Google in their browser.
 */
function GoogleOneTapManager() {
    const { isAuthenticated, isLoading, googleLogin } = useAuthStore()

    useGoogleOneTapLogin({
        onSuccess: async (response) => {
            try {
                await googleLogin(response.credential)
            } catch {
                // Silent fail — user can click Login manually
            }
        },
        onError: () => {},
        disabled: isLoading || isAuthenticated,
        auto_select: true,
        cancel_on_tap_outside: false,
    })

    return null
}

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: 'ShotockViz — Stock Analysis Platform' },
      { name: 'description', content: 'Self-hosted stock analysis platform for Thai and US markets' },
      { name: 'theme-color', content: '#0b0d14' }
    ],
    links: [
      { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
      { rel: 'manifest', href: '/manifest.json' },
      { rel: 'stylesheet', href: appCss },
      { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
      { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossOrigin: 'anonymous' },
      { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800&display=swap' },
    ],
  }),
  shellComponent: RootDocument,
  component: RootComponent,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  )
}

function RootComponent() {
  const { initTheme } = useAppStore()
  const { checkAuth } = useAuthStore()

  // Keep websocket alive at root level
  useWebSocket()

  // Poll /api/v1/system/ready; bumps dataVersion when cache is warm
  useBackendReady()

  useEffect(() => {
    initTheme()
    checkAuth()
  }, [])

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Silent re-auth: if session is lost on refresh, One Tap re-authenticates
          automatically using the user's existing Google sign-in — no popup needed */}
      {GOOGLE_CLIENT_ID && (
        <ClientOnly>
          <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
            <GoogleOneTapManager />
          </GoogleOAuthProvider>
        </ClientOnly>
      )}
      <Navbar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>
      <StatusBar />
      <SearchModal />
      <AIChatPanel />
      <Toaster />
    </div>
  )
}
