import { test, expect, type Page } from "@playwright/test";

test("photo upload sends bytes only to storage and loads authorized thumbnail", async ({
  page,
}) => {
  await systemRoutes(page);
  await page.route("https://test.supabase.co/auth/v1/**", (route) =>
    route.fulfill({ json: session("alice") }),
  );
  let uploaded = false;
  const pixel = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP9sAAAAASUVORK5CYII=",
    "base64",
  );
  await page.route("**/api/v1/storage-nodes?*", (route) =>
    route.fulfill({
      json: [
        { id: "node", display_name: "This Windows PC", disabled_at: null },
      ],
    }),
  );
  await page.route("**/api/v1/storage-nodes/node/upload-grant", (route) => {
    expect(route.request().postDataJSON().filename).toBe("first.png");
    expect(route.request().postDataJSON().byte_size).toBe(pixel.length);
    return route.fulfill({
      json: { url: "http://127.0.0.1:8100/upload", token: "upload-ticket" },
    });
  });
  await page.route("http://127.0.0.1:8100/**", (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS")
      return route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "*",
          "Access-Control-Allow-Methods": "GET,POST",
        },
      });
    if (req.url().endsWith("/upload")) {
      expect(req.headers().authorization).toBe("Bearer upload-ticket");
      expect(req.postDataBuffer()).toEqual(pixel);
      uploaded = true;
      return route.fulfill({
        json: { status: "complete" },
        headers: { "Access-Control-Allow-Origin": "*" },
      });
    }
    expect(req.headers().authorization).toBe("Bearer read-ticket");
    return route.fulfill({
      body: pixel,
      contentType: "image/png",
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  });
  await page.route("**/api/v1/media/photo/access-grant?*", (route) =>
    route.fulfill({
      json: {
        url: "http://127.0.0.1:8100/objects/photo/thumbnail",
        token: "read-ticket",
      },
    }),
  );
  await page.route("**/api/v1/media?*", (route) =>
    route.fulfill({
      json: {
        has_more: false,
        results: uploaded
          ? [
              {
                id: "photo",
                user_id: "alice",
                device_id: "windows-pc",
                local_file_id: "opaque-id",
                original_filename: "first.png",
                file_type: "image",
                tags: [],
                thumbnail_url: null,
                created_at: "2026-09-27T00:00:00Z",
                updated_at: "2026-09-27T00:00:00Z",
              },
            ]
          : [],
      },
    }),
  );
  await page.goto("/");
  await page.getByLabel("Email address").fill("alice@example.com");
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: "Add media", exact: true }).click();
  await page
    .getByLabel("Photo", { exact: true })
    .setInputFiles({ name: "first.png", mimeType: "image/png", buffer: pixel });
  await page.getByRole("button", { name: "Upload photo", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "first.png" })).toBeVisible();
  await expect(page.locator(".media-card img")).toHaveAttribute(
    "src",
    /^blob:/,
  );
});

test("storage registration saves only metadata and supports disabling", async ({
  page,
}) => {
  await systemRoutes(page);
  await page.route("https://test.supabase.co/auth/v1/**", (route) =>
    route.fulfill({ json: session("alice") }),
  );
  await page.route("**/api/v1/media?*", (route) =>
    route.fulfill({ json: { results: [], has_more: false } }),
  );
  const nodes: Record<string, unknown>[] = [];
  await page.route("**/api/v1/storage-nodes**", async (route) => {
    expect(route.request().headers().authorization).toMatch(/^Bearer /);
    if (route.request().url().endsWith("/disable")) {
      nodes[0].disabled_at = "2026-09-27T00:00:00Z";
      return route.fulfill({ json: nodes[0] });
    }
    if (route.request().method() === "POST") {
      const data = route.request().postDataJSON();
      expect(Object.keys(data).sort()).toEqual([
        "base_url",
        "device_id",
        "display_name",
      ]);
      expect(data.base_url).toBe("http://127.0.0.1:8100");
      nodes.push({
        ...data,
        id: "test-node",
        disabled_at: null,
        created_at: "2026-09-27T00:00:00Z",
      });
      return route.fulfill({ status: 201, json: nodes[0] });
    }
    return route.fulfill({ json: nodes });
  });
  await page.goto("/");
  await page.getByLabel("Email address").fill("alice@example.com");
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your story starts here" }),
  ).toBeVisible();
  await navigate(page, "Connections");
  await page
    .getByRole("button", { name: "Register storage", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Storage registered");
  await expect(page.locator(".storage-list")).toContainText(
    "connectivity not verified",
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Disable This Windows PC" }).click();
  await expect(page.locator(".storage-list")).toContainText("Disabled");
  await expect(page.getByRole("status")).toContainText("No files were deleted");
});

async function systemRoutes(page: Page) {
  await page.route("**/health", (route) =>
    route.fulfill({ json: { status: "ok", service: "MediaNest AI" } }),
  );
  await page.route("**/db-health", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Database is not configured" },
    }),
  );
}
async function navigate(page: Page, label: string) {
  const menu = page.getByRole("button", { name: "Open navigation" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation").getByRole("link", { name: label }).click();
}
test("sample gallery filters, details, keyboard dismissal and responsive layout", async ({
  page,
}, testInfo) => {
  await systemRoutes(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Explore sample library" }).click();
  await expect(
    page.getByRole("heading", { name: "A home for your moments." }),
  ).toBeVisible();
  await expect(page.locator(".media-card")).toHaveCount(6);
  await page.getByRole("button", { name: "Videos", exact: true }).click();
  await expect(page.locator(".media-card")).toHaveCount(1);
  await page.getByRole("button", { name: "All media", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search by exact tag" })
    .fill("Nature");
  await page.getByRole("button", { name: "Submit tag search" }).click();
  await expect(page.locator(".media-card")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Open The quiet side of the lake.jpg" })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText("not a stored file");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Clear search" }).click();
  await page.getByRole("button", { name: "List view" }).click();
  await expect(page.locator(".list-layout")).toBeVisible();
  await page.getByRole("button", { name: "Grid view" }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.evaluate(() => {
    (document.activeElement as HTMLElement)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({
    path: testInfo.outputPath("library.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Add media", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "No file will be selected or uploaded",
  );
  await page.getByRole("button", { name: "Close details" }).click();
  await navigate(page, "Connections");
  await expect(page.getByText("Database is not configured")).toBeVisible();
  await navigate(page, "Face search");
  await expect(
    page.getByRole("button", { name: "Search faces", exact: true }),
  ).toBeDisabled();
});

function token(user: string) {
  const payload = Buffer.from(
    JSON.stringify({
      sub: user,
      aud: "authenticated",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  ).toString("base64url");
  return "eyJhbGciOiJIUzI1NiJ9." + payload + ".test-signature";
}
function session(user: string) {
  return {
    access_token: token(user),
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "test-refresh-" + user,
    user: {
      id: user,
      aud: "authenticated",
      role: "authenticated",
      email: user + "@example.com",
      app_metadata: {},
      user_metadata: {},
      created_at: "2026-01-01T00:00:00Z",
    },
  };
}
test("sign-in sends bearer credentials and account switch clears private records", async ({
  page,
}) => {
  await systemRoutes(page);
  await page.route("https://test.supabase.co/auth/v1/**", async (route) => {
    if (route.request().url().includes("/logout")) {
      await route.fulfill({ status: 204 });
      return;
    }
    if (route.request().url().includes("/token")) {
      const user = (route.request().postDataJSON().email as string).split(
        "@",
      )[0];
      await route.fulfill({ json: session(user) });
      return;
    }
    await route.fulfill({ json: session("alice").user });
  });
  await page.route("**/api/v1/media?*", async (route) => {
    const auth = route.request().headers().authorization;
    expect(auth).toMatch(/^Bearer /);
    const user = JSON.parse(
      Buffer.from(auth!.split(".")[1], "base64").toString(),
    ).sub as string;
    await route.fulfill({
      json: {
        has_more: false,
        results: [
          {
            id: user + "-media",
            user_id: user,
            device_id: "nas",
            local_file_id: user + "-private.jpg",
            file_type: "image",
            thumbnail_url: null,
            tags: ["Family"],
            transcription: null,
            created_at: "2026-09-01T12:00:00Z",
            updated_at: "2026-09-01T12:00:00Z",
          },
        ],
      },
    });
  });
  await page.goto("/");
  async function signIn(user: string) {
    await page.getByLabel("Email address").fill(user + "@example.com");
    await page.getByLabel("Password", { exact: true }).fill("test-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
  }
  await signIn("alice");
  await expect(
    page.getByRole("heading", { name: "alice-private.jpg" }),
  ).toBeVisible();
  if (await page.getByRole("button", { name: "Open navigation" }).isVisible())
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("button", { name: /alice@example.com.*Sign out/ })
    .click();
  await signIn("bob");
  await expect(
    page.getByRole("heading", { name: "bob-private.jpg" }),
  ).toBeVisible();
  await expect(page.getByText("alice-private.jpg")).toHaveCount(0);
});
test("login errors remain visible instead of becoming sample records", async ({
  page,
}) => {
  await systemRoutes(page);
  await page.route("https://test.supabase.co/auth/v1/token**", (route) =>
    route.fulfill({ status: 400, json: { msg: "Invalid login credentials" } }),
  );
  await page.goto("/");
  await page.getByLabel("Email address").fill("invalid@example.com");
  await page.getByLabel("Password", { exact: true }).fill("incorrect");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Invalid login credentials",
  );
  await expect(page.locator(".media-card")).toHaveCount(0);
});

test("library retries failures, paginates and exposes face validation", async ({
  page,
}) => {
  await systemRoutes(page);
  await page.route("https://test.supabase.co/auth/v1/**", (route) =>
    route.fulfill({ json: session("alice") }),
  );
  let failure = true;
  await page.route("**/api/v1/media?*", (route) => {
    if (failure)
      return route.fulfill({
        status: 502,
        json: { detail: "Media library request failed" },
      });
    const offset = new URL(route.request().url()).searchParams.get("offset");
    return route.fulfill({ json: { results: [], has_more: offset === "0" } });
  });
  await page.route("**/api/v1/media/search-face", (route) => {
    expect(route.request().postDataJSON().embedding).toHaveLength(512);
    return route.fulfill({ json: { matches: [] } });
  });
  await page.goto("/");
  await page.getByLabel("Email address").fill("alice@example.com");
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Media library request failed",
  );
  await expect(page.locator(".media-card")).toHaveCount(0);
  failure = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your story starts here" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByText("Page 1", { exact: true })).toBeVisible();
  await navigate(page, "Face search");
  await page.getByLabel("Face embedding (JSON)").fill("[1,2]");
  await page.getByRole("button", { name: "Search faces", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("512");
  await page
    .getByLabel("Face embedding (JSON)")
    .fill(JSON.stringify(Array(512).fill(0.1)));
  await page.getByRole("button", { name: "Search faces", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "0 face matches" }),
  ).toBeVisible();
});
