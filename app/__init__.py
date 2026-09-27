"""Media Archive Cloud API package."""

# HTTPX uses certifi by default, which cannot see private roots installed by
# Windows policy (for example, an HTTPS-inspection proxy). As this is the
# application package—not a reusable library—install the native trust-store
# adapter before Supabase/HTTPX create any SSL contexts.
import truststore

truststore.inject_into_ssl()

__version__ = "0.2.0"
