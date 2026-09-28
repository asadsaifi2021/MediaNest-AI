import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, extname, sep } from "node:path";
import { chromium } from "@playwright/test";

const root = resolve(fileURLToPath(new URL("../dist/", import.meta.url)));
const server = createServer(async (req, res) => {
  const name = new URL(req.url, "http://localhost").pathname;
  const target = resolve(root, "." + name);
  if (target !== root && !target.startsWith(root + sep)) {
    res.writeHead(403).end(); return;
  }
  const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
    ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json" };
  try {
    const data = await readFile(name === "/" ? resolve(root, "index.html") : target);
    res.writeHead(200, { "Content-Type": types[extname(name)] || "text/html" }).end(data);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = "http://127.0.0.1:" + server.address().port;
let browser;
try {
  browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(origin);
  await page.evaluate(() => Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, reject) => setTimeout(() => reject(new Error("Service worker did not register")), 10000)),
  ]));
  await page.reload();
  const cdp = await context.newCDPSession(page);
  const manifest = await cdp.send("Page.getAppManifest");
  assert.equal(JSON.parse(manifest.data).name, "MediaNest AI");
  assert.equal(manifest.errors.length, 0);
  const entries = await page.evaluate(async () => {
    const keys = await caches.keys();
    return Promise.all(keys.map(async key => (await (await caches.open(key)).keys()).map(r => new URL(r.url).pathname)));
  });
  assert.deepEqual(entries.flat(), ["/offline.html"]);
  await context.setOffline(true);
  await page.goto(origin + "/private-library");
  assert.match(await page.textContent("body"), /MediaNest needs a connection/);
  console.log("PWA manifest, registration, cache privacy and offline fallback passed.");
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
