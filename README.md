# cloudways-api

[![CI](https://github.com/projectassistant-webdev/cloudways-api/actions/workflows/test.yml/badge.svg)](https://github.com/projectassistant-webdev/cloudways-api/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A comprehensive Python CLI for [Cloudways API v2](https://developers.cloudways.com/) operations. Manage servers, databases, SSH sessions, SSL certificates, security, deployments, and provisioning from the command line.

**36 command modules** | **1,400+ tests** | **Async httpx client** | **Rich terminal output**

## Features

- **Database workflows** -- Pull, push, restore, and sync databases between local Docker containers and remote Cloudways servers with automatic URL replacement
- **SSH management** -- Interactive sessions, remote command execution, key management, and SFTP user administration
- **Security suite** -- IP whitelisting, Let's Encrypt and custom SSL certificates, Imunify360 app security, server-level firewalls and geo-blocking
- **Server lifecycle** -- Start, stop, restart, rename, delete servers; provision new servers and apps from templates or interactive prompts
- **Git deployment** -- Clone repos, pull branches, view deployment history
- **Monitoring** -- Server graphs, app analytics, traffic analysis, PHP/MySQL slow logs, cron monitoring
- **Backup & disk** -- On-demand backups, backup scheduling, disk cleanup
- **Environment capture** -- Extract `.env` files from remote Bedrock and traditional WordPress installations
- **Capistrano generation** -- Auto-generate deployment configs with Bitbucket Pipelines support
- **Multi-account support** -- Manage multiple Cloudways accounts with environment variable interpolation
- **Claude Code integration** -- Includes a `.claude/skills/cloudways/` skill for AI-assisted server operations

## Installation

### From source

```bash
git clone https://github.com/projectassistant-webdev/cloudways-api.git
cd cloudways-api
pip install -r requirements.txt
pip install -e .
```

### Docker

```bash
git clone https://github.com/projectassistant-webdev/cloudways-api.git
cd cloudways-api
docker compose build
docker compose run --rm app cloudways --version
```

## Quick Start

### 1. Set up credentials

Create `~/.cloudways/accounts.yml`:

```yaml
accounts:
  primary:
    email: you@example.com
    api_key: ${CLOUDWAYS_API_KEY}
```

Store the actual API key in `~/.cloudways/.env`:

```
CLOUDWAYS_API_KEY=your-api-key-here
```

Get your API key from the [Cloudways Platform API](https://platform.cloudways.com/api) section.

### 2. Configure your project

Create a `project-config.yml` in your project (or set `CLOUDWAYS_PROJECT_CONFIG`):

```yaml
hosting:
  cloudways:
    account: primary
    server:
      id: 1234567
      ssh_user: master_xxxxxxxxx
      ssh_host: 123.45.67.89
    environments:
      production:
        app_id: 9876543
        domain: example.com
        webroot: public_html/current
      staging:
        app_id: 9876544
        domain: staging.example.com
        webroot: public_html/current
    database:
      local_container: my-mariadb
      local_db_name: wordpress
      url_replace_method: wp-cli
```

### 3. Verify setup

```bash
cloudways verify-setup
cloudways info
```

## Command Groups

| Group | Commands | Description |
|-------|----------|-------------|
| **info** | `info` | Server and application details with Rich-formatted output |
| **server** | `start`, `stop`, `restart`, `delete`, `rename` | Server lifecycle management |
| **db-pull/push/restore/sync** | 4 commands | Database transfer between local and remote |
| **ssh** | `ssh`, `ssh-setup` | Interactive SSH and remote command execution |
| **ssh-key** | `add`, `delete`, `rename` | SSH public key management |
| **ssh-user** | `create`, `list`, `password`, `delete` | SSH/SFTP user administration |
| **deploy-key** | `add`, `delete` | Git deploy key management |
| **security whitelist** | `list`, `add`, `remove`, `blacklist-check`, `whitelist-siab`, `whitelist-adminer` | IP whitelisting for SSH, MySQL, Web SSH, Adminer |
| **security ssl** | `install`, `renew`, `auto`, `revoke`, `install-custom`, `remove-custom` | Let's Encrypt and custom SSL certificates |
| **backup** | `run`, `settings get`, `settings set` | On-demand backups and scheduling |
| **disk** | `settings get`, `cleanup` | Disk management and cleanup |
| **git** | `clone`, `pull`, `branches`, `history` | Git deployment operations |
| **app** | `webroot get`, `webroot set` | Application configuration |
| **services** | `list`, `restart` | PHP, MariaDB, nginx service management |
| **provision** | `server`, `app`, `staging` | Server and application provisioning |
| **env** | `env-capture`, `env-generate` | Environment variable management |
| **monitor** | `server-summary`, `server-usage`, `server-graph`, `app-summary`, `traffic`, `php`, `mysql`, `cron` | Server and application monitoring |
| **alerts** | `list`, `read`, `channels` | Alert and notification management |
| **cloudflare** | `analytics`, `security`, `logpush` | Cloudflare integration |
| **copilot** | `plans`, `status`, `subscribe`, `settings`, `insights` | Cloudways Copilot management |
| **safeupdates** | `check`, `list`, `enable`, `disable`, `run`, `schedule`, `history` | WordPress safe update management |
| **appsec** | `status`, `scan`, `files`, `events`, `incidents`, `activate` | Imunify360 app security |
| **serversec** | `incidents`, `ips`, `geoblock`, `stats`, `firewall`, `apps` | Server-level security |
| **team** | `list`, `add`, `update`, `remove` | Team member management |
| **setup** | `setup-project`, `setup-bedrock`, `verify-setup`, `capistrano`, `reset-permissions`, `init-shared` | Project setup and utilities |

## Usage Examples

### Pull a database from production

```bash
cloudways db-pull production                  # Stream mode (pipes over SSH)
cloudways db-pull production --safe           # File mode (SCP download)
cloudways db-pull production --skip-transients  # Exclude cache tables
```

### Push a database to staging

```bash
cloudways db-push staging                     # Auto-backup + URL replacement
cloudways db-push staging --skip-backup       # Skip the remote backup
```

### Deploy via git

```bash
cloudways git pull production --branch main --wait
```

### Provision a new server

```bash
cloudways provision server                              # Interactive prompts
cloudways provision server -r nyc3 -s 2GB -l my-server  # Non-interactive
cloudways provision server --from-template server.yml   # From YAML template
```

### SSH and remote commands

```bash
cloudways ssh production                      # Interactive session
cloudways ssh production -- wp plugin list    # Execute remote command
cloudways ssh production -- wp cache flush    # Flush WordPress cache
```

### SSL certificate management

```bash
cloudways security ssl install production --email admin@example.com --domains example.com,www.example.com
cloudways security ssl auto production --enable
```

### Security audit

```bash
cloudways appsec scan production --wait
cloudways serversec incidents
cloudways serversec firewall get
```

## Configuration

### Credentials (`~/.cloudways/accounts.yml`)

Supports multiple accounts with environment variable interpolation:

```yaml
accounts:
  primary:
    email: you@example.com
    api_key: ${CLOUDWAYS_API_KEY_PRIMARY}
  agency:
    email: agency@example.com
    api_key: ${CLOUDWAYS_API_KEY_AGENCY}
```

Environment variables `CLOUDWAYS_EMAIL` and `CLOUDWAYS_API_KEY` override loaded values when set.

### Project Config

The CLI discovers `project-config.yml` by walking up from the current directory (up to 5 levels). Override with `CLOUDWAYS_PROJECT_CONFIG`.

### Provisioning Templates

YAML templates automate server and app provisioning:

```yaml
provision:
  type: server
  region: nyc3
  size: 2GB
  server_label: "${label}"
  app_label: my-app
```

## Claude Code Integration

This project includes a Claude Code skill at `.claude/skills/cloudways/` that enables AI-assisted Cloudways operations. When installed as a tool in a project, Claude Code can execute cloudways commands contextually based on your project's hosting configuration.

See [SKILL.md](.claude/skills/cloudways/SKILL.md) for setup and usage details.

## Development

### Running tests

```bash
# All tests
pytest tests/ -x -q --tb=short

# With coverage
pytest tests/ --cov=cloudways_api --cov-report=html

# Specific module
pytest tests/test_db_pull.py -v

# Via Docker
docker compose run --rm app pytest tests/ -v
```

Tests use mocked HTTP transports (`httpx.MockTransport`) -- no real API calls or services needed.

### Linting

```bash
ruff check cloudways_api/ tests/
```

### Project Structure

```
cloudways-api/
  cloudways_api/
    cli.py                 # Typer CLI entry point
    client.py              # Async Cloudways API client (httpx)
    config.py              # Project config loader
    credentials.py         # Account credential loader
    commands/              # 36 command modules
      db_pull.py, db_push.py, db_restore.py, db_sync.py
      ssh_cmd.py, ssh_key.py, ssh_user.py, ssh_setup.py
      security.py, server.py, backup.py, git.py, ...
      provision/
        server.py, app.py, staging.py
  tests/                   # 1,400+ tests
  .claude/skills/cloudways/  # Claude Code skill
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for your changes
4. Ensure all tests pass (`pytest tests/ -x -q`)
5. Ensure linting passes (`ruff check cloudways_api/ tests/`)
6. Submit a pull request

## License

[MIT](LICENSE)
