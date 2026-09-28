import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  if (
    Object.entries(env).some(
      ([name, value]) =>
        /SECRET|SERVICE_ROLE|HMAC/i.test(name) ||
        value.startsWith("sb_secret_"),
    )
  ) {
    throw new Error(
      "Server credentials are present in VITE_ configuration. Remove them before starting or building the frontend.",
    );
  }
  return {
    plugins: [react()],
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            auth: ["@supabase/supabase-js"],
            query: ["@tanstack/react-query"],
          },
        },
      },
    },
    server: {
      proxy: {
        "/api": "http://127.0.0.1:8000",
        "/health": "http://127.0.0.1:8000",
        "/db-health": "http://127.0.0.1:8000",
      },
    },
  };
});
