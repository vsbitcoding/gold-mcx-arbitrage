import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served at https://arbitrage.bitcoding.ai/admin/ (nginx SPA try_files resolves
// /admin/ to /var/www/arbitrage/admin/index.html). base must match that path.
export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  server: {
    host: true,
    port: 5174,
    proxy: { "/api": "http://localhost:8000" },
  },
  build: { outDir: "dist" },
});
