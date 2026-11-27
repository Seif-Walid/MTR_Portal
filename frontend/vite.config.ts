import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    // Installable app on Android, iOS, Windows, macOS, Linux from this one
    // codebase: web manifest + a service worker that caches the app shell.
    VitePWA({
      // New builds wait for the user to click "Reload" (see PwaUpdater) so a
      // half-filled form never gets wiped by a silent swap.
      registerType: 'prompt',
      injectRegister: false,
      includeAssets: ['logo.png', 'icons/apple-touch-icon.png', 'icons/favicon-64.png'],
      manifest: {
        id: '/',
        name: 'Mind·Tech Robotics Portal',
        short_name: 'MTR Portal',
        description: 'Mind·Tech Robotics operations portal — tasks, events, inventory, finance.',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'any',
        background_color: '#ffffff',
        theme_color: '#1f63e0',
        categories: ['productivity', 'education'],
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
        shortcuts: [
          { name: 'Tasks', url: '/tasks', icons: [{ src: '/icons/icon-192.png', sizes: '192x192' }] },
          { name: 'Calendar', url: '/calendar', icons: [{ src: '/icons/icon-192.png', sizes: '192x192' }] },
          { name: 'Assistant', url: '/assistant', icons: [{ src: '/icons/icon-192.png', sizes: '192x192' }] },
        ],
      },
      workbox: {
        // App shell only. API responses are per-person and permissioned, so
        // they are never cached — always fresh from the server.
        globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
        maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/\.well-known\//],
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      // same-origin in dev: session cookie just works
      '/api': process.env.API_PROXY ?? 'http://localhost:8000',
      // OAuth discovery for outside AI agents (see backend ai/oauth.py)
      '/.well-known/oauth-': process.env.API_PROXY ?? 'http://localhost:8000',
    },
  },
});
