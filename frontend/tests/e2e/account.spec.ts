import { test, expect, type Page } from "@playwright/test";

async function setup(page: Page, fail = false) {
  let user = {
    id: "alice",
    email: "alice@example.com",
    aud: "authenticated",
    role: "authenticated",
    user_metadata: {} as Record<string, string>,
    app_metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    email_confirmed_at: "2026-01-01T00:00:00Z",
    new_email: "",
  };
  const updates: Record<string, unknown>[] = [];
  const scopes: string[] = [];
  await page.route("**/health", (r) => r.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/v1/media?*", (r) =>
    r.fulfill({ json: { results: [], has_more: false } }),
  );
  await page.route("https://test.supabase.co/auth/v1/**", (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.pathname.endsWith("/token"))
      return route.fulfill({
        json: {
          access_token:
            "eyJhbGciOiJIUzI1NiJ9." +
            Buffer.from(
              JSON.stringify({
                sub: "alice",
                exp: Math.floor(Date.now() / 1000) + 3600,
              }),
            ).toString("base64url") +
            ".test",
          token_type: "bearer",
          refresh_token: "test-refresh",
          expires_in: 3600,
          user,
        },
      });
    if (url.pathname.endsWith("/logout")) {
      scopes.push(url.searchParams.get("scope") || "");
      return route.fulfill({ status: 204 });
    }
    if (req.method() === "PUT") {
      const body = req.postDataJSON();
      updates.push(body);
      if (fail)
        return route.fulfill({
          status: 400,
          json: { msg: "Update rejected for this test" },
        });
      if (body.data)
        user = {
          ...user,
          user_metadata: { ...user.user_metadata, ...body.data },
        };
      if (body.email) user = { ...user, new_email: body.email };
    }
    return route.fulfill({ json: user });
  });
  await page.goto("/");
  await page.getByLabel("Email address").fill("alice@example.com");
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your story starts here" }),
  ).toBeVisible();
  await page.goto("/account");
  await expect(
    page.getByRole("heading", { name: "Profile", exact: true }),
  ).toBeVisible();
  return { updates, scopes };
}

test("profile persists, email stays pending, and passwords go directly to Auth", async ({
  page,
}) => {
  const { updates } = await setup(page);
  await page.getByLabel("Display name").fill("Asad");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByRole("status")).toContainText("Profile saved");
  expect(updates[0]).toMatchObject({ data: { full_name: "Asad" } });
  await page.reload();
  await expect(page.getByLabel("Display name")).toHaveValue("Asad");
  await page.getByLabel("New email address").fill("new@example.com");
  await page.getByRole("button", { name: "Request email change" }).click();
  await expect(page.getByText(/Pending email change:/)).toContainText(
    "new@example.com",
  );
  await expect(page.locator(".account-facts")).toContainText(
    "alice@example.com",
  );
  await page
    .getByLabel("Current password", { exact: true })
    .fill("old-password");
  await page
    .getByLabel("New password", { exact: true })
    .fill("new-long-password");
  await page.getByLabel("Confirm new password").fill("different-password");
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByRole("alert")).toContainText("do not match");
  expect(updates).toHaveLength(2);
  await page.getByLabel("Confirm new password").fill("new-long-password");
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Password updated" }),
  ).toBeVisible();
  expect(updates[2]).toMatchObject({
    password: "new-long-password",
    current_password: "old-password",
  });
  await expect(
    page.getByLabel("Current password", { exact: true }),
  ).toHaveValue("");
  await expect(page.getByLabel("New password", { exact: true })).toHaveValue(
    "",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("session controls use the correct scope and forgot-password works while signed in", async ({
  page,
}) => {
  const { scopes } = await setup(page);
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Sign out other sessions" }).click();
  await expect(page.getByRole("status")).toContainText(
    "This browser is still signed in",
  );
  expect(scopes).toEqual(["others"]);
  await page
    .getByRole("link", { name: "Forgot your current password?" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Forgot your password?" }),
  ).toBeVisible();
  await page.goto("/account");
  await page.getByRole("button", { name: "Sign out of this browser" }).click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  expect(scopes).toEqual(["others", "local"]);
});

test("failed updates do not claim success and sample mode cannot edit accounts", async ({
  page,
}) => {
  await setup(page, true);
  await page.getByLabel("Display name").fill("Unsaved");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByRole("alert")).toContainText("Update rejected");
  await expect(page.getByText("Profile saved.", { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Sign out of this browser" }).click();
  await page.getByRole("button", { name: "Explore sample library" }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in to manage your account" }),
  ).toBeVisible();
  await expect(page.getByLabel("Display name")).toHaveCount(0);
});
