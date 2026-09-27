import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@pmagent/ui", "@pmagent/shared", "@pmagent/api-client"],
  // The browser tests build into their own folder: `next build` empties its output folder,
  // which would break a `next dev` running from the default .next at the same time.
  distDir: process.env.PMAGENT_NEXT_DIST_DIR || ".next",
};

export default nextConfig;
