import { defineConfig } from 'vite'

export default defineConfig({
  publicDir: '../images',
  server: {
    port: 5173,
    proxy: {
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
