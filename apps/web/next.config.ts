import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@pmagent/ui", "@pmagent/shared", "@pmagent/api-client"],
};

export default nextConfig;
