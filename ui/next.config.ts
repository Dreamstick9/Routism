import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Normal Next production server (docker-compose ui service on :3000).
  // API runs separately on :8000; browser talks to it via NEXT_PUBLIC_ROUTISM_API.
};

export default nextConfig;
