import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND = "http://127.0.0.1:8010";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,                 // reachable from a phone on the same network
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": BACKEND,
      "/q": BACKEND,            // signed public PDF links minted by the API
    },
  },
});
