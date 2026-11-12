import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 서버에서만 /api 를 백엔드로 전달한다(배포에서는 vercel.json rewrite 가 담당).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.DEV_API_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: { '/api': { target, changeOrigin: false } }
    }
  }
})
