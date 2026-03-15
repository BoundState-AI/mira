import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  define: {
    global: "globalThis",
  },
  server: {
    host: "::",
    port: 8080,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (requestPath) => {
          // Keep /api prefix for MUA v10 to support backend builds that only
          // expose /api/mua/v10, while preserving legacy rewrite behavior for
          // the rest of the API surface.
          if (requestPath.startsWith('/api/mua/v10')) {
            return requestPath;
          }
          return requestPath.replace(/^\/api/, '');
        },
        timeout: 600000, // 10 minutes for long-running extractions
        proxyTimeout: 600000,
        selfHandleResponse: false, // Let proxy handle response normally
        configure: (proxy) => {
          // Keep connections alive for long-running requests (FORGE compile)
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setSocketKeepAlive(true, 30000);
          });
          proxy.on('error', (err, req, res) => {
            console.error('Proxy error:', err.message);
            if (!res.headersSent) {
              res.writeHead(502, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ error: 'Proxy error', message: err.message }));
            }
          });
          proxy.on('proxyRes', (proxyRes, req) => {
            console.log(`[Proxy] ${req.method} ${req.url} -> ${proxyRes.statusCode}`);
          });
        },
      },
    },
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
