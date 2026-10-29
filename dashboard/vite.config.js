import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages serves at https://<user>.github.io/cfd-shadow/
// Local `npm run dev` still uses "/".
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/cfd-shadow/" : "/",
  server: {
    // PolyU tree dashboard uses 5174 — keep Shadow on its own port.
    host: "127.0.0.1",
    port: 5175,
    strictPort: true,
  },
}));
