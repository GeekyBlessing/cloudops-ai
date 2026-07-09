import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Standard Vite + React config. Dev server runs on 5173 by default, which
// is what the backend's CORS allow-list (core/config.py's cors_origins)
// is configured to accept out of the box.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
