# Sign in, sign up, confirmation and password recovery

The app uses Supabase Auth directly with its publishable key. Passwords are
never sent to the MediaNest API or stored in application tables. Existing
accounts still sign in with the same credentials.

## Dashboard setup (no SQL migration needed)

In Supabase → Authentication → URL Configuration:

1. Set Site URL to `http://127.0.0.1:5173`.
2. Add these exact Redirect URLs:
   - `http://127.0.0.1:5173/auth/callback`
   - `http://127.0.0.1:5173/auth/reset-password`
   - `http://localhost:5173/auth/callback`
   - `http://localhost:5173/auth/reset-password`
3. Save.

Under Authentication settings, enable email/password signup and keep email
confirmation enabled. Both are already enabled on the current project as of
the implementation check. Match Supabase's minimum password length to the
app's 12-character minimum. The provider remains authoritative for password
policy, rate limits, and any additional security requirements.

Keep the standard confirmation/reset email links using `{{ .ConfirmationURL }}`;
do not replace them with a bare site URL. Custom templates must preserve the
verification step and requested redirect path.

For signups outside your Supabase project team, configure custom SMTP in the
dashboard. The default sender restricts recipients and has low rate limits.
Do not switch off confirmation just to make emails work. Store SMTP credentials
only in Supabase settings, never in React. Production should also configure
Supabase abuse protection/CAPTCHA before opening registration publicly; this
version does not include a CAPTCHA widget.

## Try the workflow

1. Refresh the app. Sign out if already signed in.
2. Choose **Create an account**.
3. Enter an email and a password of at least 12 characters; confirm it.
4. Click **Create account** and open the newest confirmation email in the
   **same browser and device** that submitted the form.
5. The link verifies the session and opens the private library.
6. Sign out and sign in with the new account to verify password login.
7. Test **Forgot password?**, open its email link in the same browser, enter
   and confirm the new password, and save.

PKCE stores a verifier in the requesting browser. Switching between localhost
and 127.0.0.1, changing browser profiles, using incognito for only one step, or
opening mail links in another browser can prevent verification. If that happens,
request another link from the browser you intend to use.

Confirmation resend and password-reset requests have a UI cooldown; server
limits are still authoritative. Responses avoid claiming whether a particular
account exists. Invalid or expired links show recovery instructions rather
than exposing codes/tokens in the page or retaining them in the address bar.

An account has its own empty library; signing up does not grant access to
another user's PC registration or files. The current single-PC upload setup
is tied to its registered owner and is not a family-sharing implementation.

## Deployment and verification limits

Add exact HTTPS production callback/reset URLs and update Site URL for deployment.
Your frontend host must serve index.html for /auth/* routes. Supabase rotates
and persists browser sessions; private query caches are cleared on account
changes/signout. Signout is local to the current browser session. Password
recovery uses Supabase's session and revocation behavior; do not assume every
already-issued access token is instantly revoked.

Automated desktop/mobile tests mock Supabase email endpoints and cover signup,
confirmation, session restoration, password reset, resend, errors, and isolation
on account switching. They do not send real emails. A real mailbox round trip,
dashboard redirect configuration, and SMTP delivery remain deployment checks.

References:
- https://supabase.com/docs/guides/auth/passwords
- https://supabase.com/docs/guides/auth/redirect-urls
- https://supabase.com/docs/guides/auth/auth-smtp
- https://supabase.com/docs/guides/auth/sessions/pkce-flow
