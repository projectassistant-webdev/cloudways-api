# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-16

### Added

- Initial public release
- 36 command modules covering Cloudways API v2 operations
- Async httpx-based API client with OAuth token management
- Database pull, push, restore, and sync workflows
- SSH session management and remote command execution
- SSH key, user, and deploy key administration
- Security: IP whitelisting, SSL certificate management (Let's Encrypt + custom)
- Server lifecycle: start, stop, restart, delete, rename, provision
- Application management: webroot, services, git deployment
- Monitoring: server graphs, app analytics, traffic analysis, PHP/MySQL logs
- Backup and disk management
- Environment capture for Bedrock and traditional WordPress
- Capistrano deployment config generation
- Multi-account credential management with env var interpolation
- Provisioning templates (YAML) for servers and apps
- Alert and notification channel management
- Cloudflare analytics integration
- Copilot management
- SafeUpdates management
- Imunify360 app security (appsec)
- Server security suite (serversec)
- Team member management
- Claude Code skill for AI-assisted operations
- 1,400+ tests with mocked HTTP transports
- GitHub Actions CI workflow
