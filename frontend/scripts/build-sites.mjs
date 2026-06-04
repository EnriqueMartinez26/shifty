import { mkdirSync, readdirSync, renameSync, rmSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";

const distDir = path.resolve("dist");
const tmpDir = path.join(distDir, ".sites-tmp");
const clientDir = path.join(distDir, "client");
const serverDir = path.join(distDir, "server");

if (!existsSync(distDir)) {
  throw new Error("No se encontró dist/. Ejecutá vite build antes de preparar Sites.");
}

rmSync(tmpDir, { recursive: true, force: true });
mkdirSync(tmpDir, { recursive: true });

for (const entry of readdirSync(distDir)) {
  if (entry === ".sites-tmp") {
    continue;
  }
  renameSync(path.join(distDir, entry), path.join(tmpDir, entry));
}

mkdirSync(clientDir, { recursive: true });
for (const entry of readdirSync(tmpDir)) {
  renameSync(path.join(tmpDir, entry), path.join(clientDir, entry));
}
rmSync(tmpDir, { recursive: true, force: true });

mkdirSync(serverDir, { recursive: true });
writeFileSync(
  path.join(serverDir, "index.js"),
  `const FILE_EXTENSION_RE = /\\.[a-zA-Z0-9]+$/;

export default {
  async fetch(request, env) {
    const assetResponse = await env.ASSETS.fetch(request);
    if (assetResponse.status !== 404) {
      return assetResponse;
    }

    if (!["GET", "HEAD"].includes(request.method)) {
      return assetResponse;
    }

    const url = new URL(request.url);
    if (FILE_EXTENSION_RE.test(url.pathname)) {
      return assetResponse;
    }

    return env.ASSETS.fetch(new Request(new URL("/index.html", request.url), request));
  },
};
`,
);
