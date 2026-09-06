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
  build: {
    rollupOptions: {
      output: {
        // bd:shotockviz-mj8 — Vite's client and SSR environments (nitro/vite
        // multi-environment build) independently resolve the content hash for
        // `@/styles.css?url` (__root.tsx) and land on two DIFFERENT, mutually
        // exclusive hashes for the same source file: the SSR bundle bakes a
        // literal `styles-<hashA>.css` string into the compiled route module
        // that is never written to `public/assets` at all, while the client
        // build emits the real, served file under `styles-<hashB>.css`.
        // React 19's stylesheet-precedence hydration then keeps BOTH <link>
        // tags (they dedupe by href, and the hrefs differ) — one 404s.
        // Reproduced on a from-scratch build of the initial commit
        // (1b6ff0d) too, so this is not new: it has existed since project
        // inception, just invisible because the live client-side href always
        // wins and the page still renders styled. Pinning the one global
        // stylesheet to a fixed, unhashed name makes both environments
        // resolve to the identical literal string, which removes the
        // divergence outright instead of papering over the 404. Cache
        // invalidation on deploy is still covered by Nitro's per-file ETag
        // (content-hash based), not by the filename.
        assetFileNames: (assetInfo) =>
          assetInfo.names?.[0] === 'styles.css'
            ? 'assets/styles.css'
            : 'assets/[name]-[hash][extname]',
      },
    },
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
