# Account settings

Open **Account** in the sidebar after signing in. No database migration is
required: these settings use Supabase Auth and its existing user metadata.

## Available controls

- Profile: save or clear an optional display name (up to 100 characters).
  It is stored as user_metadata.full_name and used in the sidebar.
- Account details: current email, confirmation status, creation date and user ID.
  Refresh account details fetches the current record from Supabase.
- Email: request a new address. A pending address is displayed separately;
  the app does not pretend it is confirmed. Follow every required confirmation
  email, then refresh. Supabase's secure email-change setting normally requires
  approval from both addresses.
- Password: current password, a new password of at least 12 characters and
  matching confirmation. These go directly to Supabase. If the provider requires
  reauthentication, request a verification code and submit it with the password
  change. Password inputs are cleared after an attempted provider update.
- Sessions: sign out of this browser or, after confirmation, revoke other
  sessions while keeping this browser signed in.

Already-issued access tokens may remain usable until expiry after session
revocation. Downloaded media cannot be remotely erased. This section does not
list individual devices or imply instant revocation of all access.

## Supabase requirements

Keep secure email change enabled and configure email delivery and the existing
/auth/callback redirect as described in AUTH_SETUP.md. Enable the provider's
require-current-password option if you want that policy enforced for every
client, not only this form. Supabase enforces the authoritative password and
reauthentication rules. For external recipients, custom SMTP may be required.

The profile name is user-editable presentation data, never authorization data.
Account ownership continues to use the JWT subject, not names or email addresses.
Changing email does not move or duplicate the user's media records.

Account deletion, MFA enrollment, avatar file uploads, family sharing and
individual-device session management are not implemented by this section.
No media or storage registrations are deleted by these controls.

## Verification

Desktop/mobile browser tests use mocked Supabase endpoints to verify profile
persistence, pending email changes, password validation/payloads, failure states,
session scopes and read-only sample mode. Real account credentials were not
changed and no confirmation emails were sent during automated testing.

References:
- https://supabase.com/docs/reference/javascript/auth-updateuser
- https://supabase.com/docs/guides/auth/signout
