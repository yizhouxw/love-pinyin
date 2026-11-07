import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig(({ mode }) => ({
  // iOS loads both practice modules from the installed pack over the native bridge.
  resolve: {
    alias:
      mode === 'ios-offline'
        ? [
            {
              find: /^\.\.\/\.\.\/content\/(word-practice\/lessons|daily-reading-hanzi)\.json$/,
              replacement: fileURLToPath(
                new URL('../src/domain/ios-empty-content.json', import.meta.url),
              ),
            },
          ]
        : [],
  },
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
}));
