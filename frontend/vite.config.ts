import { defineConfig } from 'vite'
import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import viteReact from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { nitro } from 'nitro/vite'

const BACKEND_URL = process.env.VITE_API_URL || 'http://backend:8000'

const config = defineConfig({
  resolve: {
    // Vite 8 native tsconfig `paths` resolution — replaces vite-tsconfig-paths
    // (unmaintained transitive dep tsconfck; removed in WP-F0, 01-sara-adr-migration.md §3.3/CR-2)
    tsconfigPaths: true,
  },
  define: {
    // @tanstack/devtools-vite injects a client even when its plugin is not loaded.
    // Without the server running, the WS URL is undefined → ws://localhost/undefined.
    // Defining the variable to empty string prevents the connection attempt.
    '__TANSTACK_DEVTOOLS_WS__': JSON.stringify(''),
    '__TANSTACK_ROUTER_DEVTOOLS_WS__': JSON.stringify(''),
  },
  plugins: [
    nitro({
      rollupConfig: { external: [/^@sentry\//] },
      // Proxy /api/* to backend — Nitro handles requests before Vite proxy
      routeRules: {
        '/api/**': { proxy: BACKEND_URL + '/api/**' },
      },
      devProxy: {
        '/api': { target: BACKEND_URL, changeOrigin: true },
      },
    }),
    tailwindcss(),
    tanstackStart(),
    viteReact(),
  ],
  server: {
    host: '0.0.0.0',
    port: 3000,
    // When accessed through Caddy on port 443 (HTTPS), HMR WebSocket must also
    // use port 443 so the browser connects to wss://localhost:443 (→ Caddy → frontend:3000)
    hmr: {
      clientPort: 443,
    },
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: true,
      },
    },
  },
})

export default config
