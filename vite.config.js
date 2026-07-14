import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: true,           // ← يسمح بالوصول من أي IP
    port: 5173,
    allowedHosts: [
      'localhost',
      '.ngrok-free.app',  // ← يسمح بكل روابط ngrok
      '.ngrok.io',        // ← احتياطي
      'all'               // ← يسمح بكل شي (غير آمن للإنتاج)
    ]
  }
})