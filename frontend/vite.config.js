import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    build: {
        outDir: "dist",
        emptyOutDir: true,
        rollupOptions: {
            input: {
                console: fileURLToPath(new URL("./index.html", import.meta.url)),
                demo: fileURLToPath(new URL("./desktop-demo/index.html", import.meta.url)),
                desktop: fileURLToPath(new URL("./desktop/index.html", import.meta.url)),
            },
        },
    },
    server: {
        port: 5173,
        proxy: {
            "/api": "http://127.0.0.1:8000",
        },
    },
});
