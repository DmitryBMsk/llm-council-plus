# Global runtime settings permissions

When `AUTH_ENABLED=true`, only usernames explicitly listed in `AUTH_ADMIN_USERS`
may PATCH settings, import settings or reset defaults. The comma-separated list
uses exact, case-sensitive usernames, for example `AUTH_ADMIN_USERS=Alice,Bob`.
An empty or unset list denies all global mutations. Existing authenticated
installations must set this variable and restart to restore administrator access.
No user is promoted automatically; passwords and JWT claims do not grant this role.

Authenticated users may read defaults/current settings and export non-secret
settings. GET `/api/settings` includes `can_edit`; the Settings modal displays
read-only controls for ordinary users. Direct unauthorized writes return HTTP 403.
With `AUTH_ENABLED=false`, the existing shared local mode remains writable.

PATCH and import enforce identical supported fields, prompt lengths, provider
choices and numeric bounds. Import replaces the configuration using defaults for
omitted fields; PATCH preserves them. Unknown fields (including keys and supplied
audit metadata) are ignored and never persisted. Conversation-specific system
prompts remain available; this change does not add personal global-settings copies.

Each successful nonempty PATCH, import or reset stores an `_audit` entry inside
the settings JSON, in the same atomic replacement as the settings values. Entries
contain a monotonic version, actor, action, UTC timestamp and field names, never
prompt values or credentials. Audit metadata is excluded from API exports. Back up
the runtime settings file to retain this history. OS file locking serializes API
mutations across local worker processes; the settings volume must support flock
and atomic rename (as supported by the existing Linux/macOS deployment).
