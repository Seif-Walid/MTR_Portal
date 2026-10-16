import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // same-origin in dev: session cookie just works
      '/api': process.env.API_PROXY ?? 'http://localhost:8000',
    },
  },
});
