// `pnpm build:static` exports a static site into out/, served by the Agent Server under /app
// (../webapp.py, registered as http.app in ../langgraph.json). A static export can't contain
// the /api proxy route, so that route uses the `proxy.ts` extension, only enabled otherwise.
const staticExport = process.env.UI_STATIC_EXPORT === "1";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Don't write AGENTS.md / CLAUDE.md into ui/ (the repo's AGENTS.md is the agent's memory file).
  agentRules: false,
  pageExtensions: staticExport ? ["tsx", "ts"] : ["tsx", "ts", "proxy.ts"],
  ...(staticExport
    ? { output: "export", basePath: "/app", trailingSlash: true }
    : {
        experimental: {
          serverActions: {
            bodySizeLimit: "10mb",
          },
        },
      }),
};

export default nextConfig;
