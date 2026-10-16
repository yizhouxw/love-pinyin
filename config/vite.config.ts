import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        configure(proxy) {
          proxy.on('proxyReq', (proxyRequest, request) => {
            const incomingHost = request.headers.host;
            if (incomingHost) proxyRequest.setHeader('X-LP-Forwarded-Host', incomingHost);
          });
        },
      },
    },
  },
  build: { target: ['chrome120', 'edge120', 'firefox121', 'safari17'] },
});
