import { defineConfig } from 'vite';
import { resolve } from 'path';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [
    tailwindcss(),
  ],
  base: '/static/',
  build: {
    manifest: 'manifest.json',
    outDir: resolve('./assets'),
    rollupOptions: {
      input: {
        main: resolve('./static/src/main.js'),
      },
    },
  },
  server: {
    host: 'localhost',
    port: 5174,
    strictPort: true,
    open: false,
    cors: true,
  },
});
