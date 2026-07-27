/** Vite build config: two entry points, one per UI language (uk/en). */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  base: "./",
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  build: {
    target: "chrome105",
    minify: "esbuild",
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        en: resolve(__dirname, "index.en.html"),
      },
    },
  },
});
