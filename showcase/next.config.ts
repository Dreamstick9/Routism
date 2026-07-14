import type { NextConfig } from "next";
import path from "path";
import { fileURLToPath } from "url";

const dir = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // Host-ready: standard Next production build (npm run build && npm start)
  reactStrictMode: true,
  images: { unoptimized: true },
  // Pin turbopack root to this package (avoid parent monorepo lockfile confusion)
  turbopack: {
    root: dir,
  },
};

export default nextConfig;
