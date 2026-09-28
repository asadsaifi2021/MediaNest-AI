import { test, expect, type Page } from "@playwright/test";

function authSession() {
  return {
    access_token:
      "eyJhbGciOiJIUzI1NiJ9." +
      Buffer.from(
        JSON.stringify({
          sub: "alice",
          aud: "authenticated",
          exp: Math.floor(Date.now() / 1000) + 3600,
        }),
      ).toString("base64url") +
      ".test",
    refresh_token: "refresh-test",
    token_type: "bearer",
    expires_in: 3600,
    user: {
      id: "alice",
      aud: "authenticated",
      email: "alice@example.com",
      role: "authenticated",
      app_metadata: {},
      user_metadata: {},
      created_at: "2026-01-01T00:00:00Z",
    },
  };
}
async function routes(page: Page) {
  await page.route("**/health", (r) => r.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/v1/media?*", (r) =>
    r.fulfill({ json: { results: [], has_more: false } }),
  );
}

test("signup validates passwords, sends PKCE confirmation, and exchanges link once", async ({
  page,
}) => {
  await routes(page);
  let signups = 0;
  let exchanges = 0;
  await page.route("https://test.supabase.co/auth/v1/**", (route) => {
    const url = new URL(route.request().url());
    const data = route.request().postDataJSON();
    if (url.pathname.endsWith("/signup")) {
      signups++;
      expect(data.email).toBe("alice@example.com");
      expect(data.code_challenge).toBeTruthy();
      expect(url.searchParams.get("redirect_to")).toBe(
        "http://127.0.0.1:5174/auth/callback",
      );
      return route.fulfill({ json: { ...authSession().user, identities: [] } });
    }
    if (url.pathname.endsWith("/token")) {
      exchanges++;
      expect(data.auth_code).toBe("confirmation-code");
      expect(data.code_verifier).toBeTruthy();
      return route.fulfill({ json: authSession() });
    }
    return route.fulfill({ json: authSession().user });
  });
  await page.goto("/");
  await page.getByRole("link", { name: "Create an account" }).click();
  await page.getByLabel("Email address").fill("alice@example.com");
  await page.getByLabel("Password", { exact: true }).fill("short");
  await page.getByLabel("Confirm password").fill("short");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("12 characters");
  expect(signups).toBe(0);
  await page.getByLabel("Password", { exact: true }).fill("my-long-password");
  await page.getByLabel("Confirm password").fill("not-the-same-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("do not match");
  await page.getByLabel("Confirm password").fill("my-long-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Check your email");
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  await expect(page.getByRole("button", { name: /Resend in/ })).toBeDisabled();
  expect(signups).toBe(1);
  await page.goto("/auth/callback?code=confirmation-code");
  await expect(
    page.getByRole("heading", { name: "Your story starts here" }),
  ).toBeVisible();
  await expect(page).toHaveURL("http://127.0.0.1:5174/");
  expect(exchanges).toBe(1);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Your story starts here" }),
  ).toBeVisible();
});

test("password recovery keeps the password form visible after session exchange", async ({
  page,
}) => {
  await routes(page);
  let updated = false;
  await page.route("https://test.supabase.co/auth/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/recover")) {
      expect(url.searchParams.get("redirect_to")).toBe(
        "http://127.0.0.1:5174/auth/reset-password",
      );
      return route.fulfill({ json: {} });
    }
    if (url.pathname.endsWith("/token"))
      return route.fulfill({ json: authSession() });
    if (route.request().method() === "PUT") {
      expect(route.request().postDataJSON().password).toBe(
        "a-new-long-password",
      );
      updated = true;
    }
    return route.fulfill({ json: authSession().user });
  });
  await page.goto("/auth/forgot-password");
  await page.getByLabel("Email address").fill("alice@example.com");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("status")).toContainText("If an account exists");
  await page.goto("/auth/reset-password?code=recovery-code");
  await expect(
    page.getByRole("heading", { name: "Choose a new password." }),
  ).toBeVisible();
  await expect(page).not.toHaveURL(/code=/);
  await page
    .getByLabel("New password", { exact: true })
    .fill("a-new-long-password");
  await page.getByLabel("Confirm password").fill("a-new-long-password");
  await page.getByRole("button", { name: "Save new password" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Password updated successfully",
  );
  expect(updated).toBe(true);
  await page.getByRole("link", { name: "Go to my library" }).click();
  await expect(
    page.getByRole("heading", { name: "Your story starts here" }),
  ).toBeVisible();
});

test("expired links and direct reset URLs never show an unauthenticated password form", async ({
  page,
}) => {
  await routes(page);
  await page.goto(
    "/auth/callback?error=access_denied&error_description=private-detail",
  );
  await expect(page.getByRole("alert")).toContainText("invalid or expired");
  await expect(page).not.toHaveURL(/private-detail/);
  await page.goto("/auth/reset-password");
  await expect(
    page.getByRole("button", { name: "Save new password" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Request a password reset" }),
  ).toBeVisible();
});

test("resend and disabled signup errors are actionable", async ({ page }) => {
  await routes(page);
  await page.route("https://test.supabase.co/auth/v1/resend**", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.route("https://test.supabase.co/auth/v1/signup**", (route) =>
    route.fulfill({
      status: 422,
      json: { code: "signup_disabled", msg: "Signups not allowed" },
    }),
  );
  await page.goto("/");
  await page.getByLabel("Email address").fill("alice@example.com");
  await page.getByRole("button", { name: "Resend confirmation email" }).click();
  await expect(page.getByRole("status")).toContainText(
    "If confirmation is needed",
  );
  await page.getByRole("link", { name: "Create an account" }).click();
  await page.getByLabel("Email address").fill("alice@example.com");
  await page.getByLabel("Password", { exact: true }).fill("my-long-password");
  await page.getByLabel("Confirm password").fill("my-long-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("disabled");
});
