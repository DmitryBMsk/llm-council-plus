# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it privately via GitHub Security Advisories or by contacting the maintainers directly. Do not open a public issue.

## Supported Versions

This project is provided as-is without guaranteed maintenance. If a security issue is reported, it will be addressed on a best-effort basis on the `main` branch.

## Security Design

- **Authentication:** Optional JWT-based auth with bcrypt-hashed credentials. Passwords are hashed before persistence; plaintext is never stored by the setup wizard.
- **Conversation isolation:** When auth is enabled, users can only access their own conversations. Unauthorized access returns 404 (not 403) to prevent ID enumeration.
- **Input validation:** All API inputs are validated via Pydantic models with size limits. File uploads are type-checked and size-limited.
- **Path traversal:** Conversation IDs are validated as UUIDs with realpath checks.
- **CORS:** Restricted to known localhost origins by default.
- **Setup endpoint:** Locked after first configuration to prevent reconfiguration attacks.
