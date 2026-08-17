import { defineConfig } from 'vite';

const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: host || '127.0.0.1',
  },
  build: {
    target: 'es2020',
    outDir: 'dist',
    emptyOutDir: true,
  },
});
