# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in LLM Council, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Use GitHub's private security reporting (Security → Advisories → "Report a vulnerability")
3. Allow reasonable time for a fix before public disclosure

## Production Deployment Checklist

Before deploying to production, ensure you have completed the following:

### Required Configuration

- [ ] **Enable Authentication**: Set `AUTH_ENABLED=true` in `.env`
- [ ] **Generate JWT Secret**: Run `openssl rand -base64 32` and set `JWT_SECRET`
- [ ] **Configure Users**: Set `AUTH_USERS={"admin": "strongpassword123"}`
- [ ] **Set API Keys**: Configure `OPENROUTER_API_KEY` or use `ROUTER_TYPE=ollama`

### Security Hardening

- [ ] **Use HTTPS**: Configure SSL certificates (see `ssl/` directory)
- [ ] **Firewall**: Only expose ports 80/443, not 8001 directly
- [ ] **Environment Variables**: Use `.env.production` for production-only secrets
- [ ] **Reverse Proxy**: Use nginx to terminate SSL and proxy to backend
- [ ] **Rate Limiting**: Consider adding rate limiting at nginx level

### Example Production `.env.production`

```bash
# Production-only settings (not synced by deploy.sh)
AUTH_ENABLED=true
JWT_SECRET=<your-generated-secret>
AUTH_USERS={"admin": "secure-password", "user1": "another-password"}
```

## Security Best Practices

### API Keys

- Never commit API keys to version control
- Use environment variables for all sensitive configuration
- Rotate API keys regularly
- Use separate keys for development and production

### Authentication

- Generate strong JWT secrets: `openssl rand -base64 32`
- Use strong passwords for user accounts (min 12 characters)
- Enable `AUTH_ENABLED=true` in production

### File Uploads

- Maximum 5 attachments per message
- Maximum 5MB per file
- Maximum 20MB total per message
- Only PDF, TXT, MD, and images are allowed

### Deployment

- Use HTTPS in production
- Keep Docker images updated
- Review docker-compose.yml before deployment
- Don't expose backend ports directly to the internet

## Known Security Considerations

### Git History

If you've previously committed secrets to this repository, they may still exist in git history. To clean sensitive data:

```bash
# Install git-filter-repo
pip install git-filter-repo

# Remove .env from history
git filter-repo --path .env --invert-paths

# Force push (coordinate with team)
git push origin --force --all
```

**Important:** After cleaning history, all API keys that were ever committed should be rotated immediately.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
