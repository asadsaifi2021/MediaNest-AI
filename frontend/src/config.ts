export function validatePublicConfig(url: string, key: string): string | null {
  if (!url && !key) return "Connect Supabase to open your own library.";
  if (!url || !key) return "Set both the Supabase URL and publishable key.";
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol !== "https:" &&
      !(
        parsed.protocol === "http:" &&
        ["localhost", "127.0.0.1"].includes(parsed.hostname)
      )
    ) {
      return "Use HTTPS for Supabase (HTTP is allowed only on localhost).";
    }
  } catch {
    return "The Supabase URL is invalid.";
  }
  if (!key.startsWith("sb_publishable_")) {
    return "Use an sb_publishable_ key in the frontend. Server secrets must never be placed here.";
  }
  return null;
}
export const demoOnly = import.meta.env.VITE_DEMO_ONLY === "true";
export const supabaseUrl = demoOnly
  ? ""
  : (import.meta.env.VITE_SUPABASE_URL?.trim() ?? "");
export const publicKey = demoOnly
  ? ""
  : (import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim() ?? "");
export const configIssue = validatePublicConfig(supabaseUrl, publicKey);
export const apiUrl = demoOnly
  ? ""
  : (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
