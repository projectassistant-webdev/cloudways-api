# cloudways-api

A Docker-containerized Python CLI for Cloudways API v2 operations. Manage servers, databases, SSH sessions, environment variables, deployment configuration, and provisioning from the command line.

**Version**: 1.0.0 | **Python**: 3.13+ | **License**: MIT

## Features

Complete CLI for Cloudways API v2 operations. 50+ commands organized by functional category.

### Server & Lifecycle Management
| Command | Description |
|---------|-------------|
| `cloudways info` | Display server and application details with Rich-formatted output |
| `cloudways server stop` | Stop the configured server |
| `cloudways server start` | Start the configured server |
| `cloudways server restart` | Restart the configured server |
| `cloudways server delete` | Delete the configured server |
| `cloudways server rename` | Rename the configured server |

### Database Operations
| Command | Description |
|---------|-------------|
| `cloudways db-pull` | Pull a remote database to a local Docker container (stream or file mode) |
| `cloudways db-push` | Push a local database to a remote server with automatic backup |
| `cloudways db-restore` | Restore a remote database from a backup file |
| `cloudways db-sync` | Sync local database to remote and back (bidirectional) |

### Environment & Configuration
| Command | Description |
|---------|-------------|
| `cloudways env-capture` | Capture environment variables from remote WordPress servers (Bedrock and traditional) |
| `cloudways env-generate` | Generate environment files with variable interpolation |

### SSH & Access Management
| Command | Description |
|---------|-------------|
| `cloudways ssh` | Open interactive SSH sessions or execute remote commands |
| `cloudways ssh-setup` | Set up SSH configuration for key-based authentication |
| `cloudways ssh-key add` | Add an SSH public key to a Cloudways app user |
| `cloudways ssh-key delete` | Delete an SSH key by ID |
| `cloudways ssh-key rename` | Rename an SSH key label |
| `cloudways ssh-user create` | Create a new SSH/SFTP user |
| `cloudways ssh-user list` | List all SSH/SFTP users |
| `cloudways ssh-user password` | Reset SSH user password |
| `cloudways ssh-user delete` | Delete an SSH user |
| `cloudways deploy-key add` | Add a deploy key for git-based deployments |
| `cloudways deploy-key delete` | Delete a deploy key by ID |

### Security & IP Whitelisting
| Command | Description |
|---------|-------------|
| `cloudways security whitelist list` | List whitelisted IPs for SSH/SFTP or MySQL access |
| `cloudways security whitelist add` | Add an IP to the whitelist |
| `cloudways security whitelist remove` | Remove an IP from the whitelist |
| `cloudways security blacklist-check` | Check if an IP is blacklisted on the server |
| `cloudways security whitelist-siab` | Whitelist an IP for Web SSH (Shell-in-a-Box) access |
| `cloudways security whitelist-adminer` | Whitelist an IP for Adminer (database manager) access |

### SSL Certificate Management
| Command | Description |
|---------|-------------|
| `cloudways security ssl install` | Install a Let's Encrypt SSL certificate |
| `cloudways security ssl renew` | Manually renew a Let's Encrypt SSL certificate |
| `cloudways security ssl auto` | Enable or disable Let's Encrypt auto-renewal |
| `cloudways security ssl revoke` | Revoke a Let's Encrypt SSL certificate |
| `cloudways security ssl install-custom` | Install a custom SSL certificate from PEM files |
| `cloudways security ssl remove-custom` | Remove a custom SSL certificate |

### Backup & Disk Management
| Command | Description |
|---------|-------------|
| `cloudways backup run` | Trigger an on-demand server backup |
| `cloudways backup settings get` | Get current backup settings |
| `cloudways backup settings set` | Update backup settings |
| `cloudways disk settings get` | Get current disk settings |
| `cloudways disk cleanup` | Clean up disk space on the server |

### Git Deployment
| Command | Description |
|---------|-------------|
| `cloudways git clone` | Clone a git repository to the application |
| `cloudways git pull` | Pull from a git repository branch |
| `cloudways git branches` | List available branches from a git repository |
| `cloudways git history` | View git deployment history |

### Application Management
| Command | Description |
|---------|-------------|
| `cloudways app webroot get` | Get current web root for an application |
| `cloudways app webroot set` | Set web root for an application |
| `cloudways services list` | List all services (PHP, MariaDB, nginx, etc.) |
| `cloudways services restart` | Restart a service |

### Provisioning & Setup
| Command | Description |
|---------|-------------|
| `cloudways provision server` | Create a new DigitalOcean server on Cloudways with interactive prompts |
| `cloudways provision app` | Create a new application on an existing Cloudways server |
| `cloudways capistrano` | Generate Capistrano deployment configuration for Bedrock WordPress |
| `cloudways verify-setup` | Verify project configuration and connectivity |
| `cloudways setup-project` | Initialize project configuration |
| `cloudways setup-bedrock` | Set up Bedrock WordPress project on the server |
| `cloudways reset-permissions` | Reset file permissions on the server |
| `cloudways init-shared` | Initialize shared WordPress installation files |

## Installation

### Docker (recommended)

```bash
git clone <repository-url>
cd cloudways-api
docker compose build
```

Run commands via Docker:

```bash
docker compose run --rm app cloudways --version
docker compose run --rm app cloudways info
```

### pip (alternative)

```bash
pip install -e .
cloudways --version
```

### Dependencies

- [Typer](https://typer.tiangolo.com/) -- CLI framework
- [httpx](https://www.python-httpx.org/) -- Async HTTP client for the Cloudways API
- [PyYAML](https://pyyaml.org/) -- Configuration file parsing
- [Rich](https://rich.readthedocs.io/) -- Terminal formatting and interactive prompts

## Quick Start

### 1. Set up credentials

Create `~/.cloudways/accounts.yml`:

```yaml
accounts:
  primary:
    email: you@example.com
    api_key: ${CLOUDWAYS_API_KEY_PRIMARY}
```

Store the actual API key in `~/.cloudways/.env`:

```
CLOUDWAYS_API_KEY_PRIMARY=your-api-key-here
```

### 2. Configure your project

Add a `hosting` section to `.prism/project-config.yml` in your project root:

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
cloudways info
```

This displays server status, IP address, PHP/MariaDB versions, and per-environment application details in a Rich-formatted table.

## Command Reference

### `cloudways info`

Show server and application details for all configured environments.

```bash
cloudways info                  # all environments
cloudways info production       # single environment
```

### `cloudways db-pull`

Pull a remote WordPress database into a local Docker MySQL/MariaDB container. Detects the remote database name from `wp-config.php`, transfers the dump, and optionally runs URL replacement.

```bash
cloudways db-pull production                  # stream mode (default)
cloudways db-pull production --safe           # file mode (SFTP download)
cloudways db-pull production --skip-transients  # exclude cache/session tables
cloudways db-pull production --no-replace     # skip URL replacement
```

**Transfer modes:**

| Mode | Flag | How it works |
|------|------|-------------|
| Stream (default) | -- | Pipes `mysqldump` through SSH directly into local `mysql` |
| File | `--safe` | Dumps to remote file, downloads via SCP, then imports locally |

### `cloudways db-push`

Push a local database to a remote Cloudways server. Automatically creates a backup of the remote database before overwriting.

```bash
cloudways db-push production                  # stream mode with backup
cloudways db-push production --safe           # file mode (SCP upload)
cloudways db-push production --skip-backup    # skip remote backup
cloudways db-push production --no-replace     # skip URL replacement
cloudways db-push production --yes            # skip production confirmation
cloudways db-push staging --local-container my-db --local-db mydb
```

Production pushes require confirmation unless `--yes` is passed.

### `cloudways db-restore`

Restore a remote database from a backup file created by `db-push`.

```bash
cloudways db-restore production               # restore most recent backup
cloudways db-restore production --list        # list available backups
cloudways db-restore production --backup-file /tmp/cloudways_backup_mydb_20260206.sql.gz
```

### `cloudways env-capture`

Capture environment variables from a remote server. Auto-detects Bedrock (`.env`) versus traditional (`wp-config.php`) WordPress installations.

```bash
cloudways env-capture production              # write to .env.production
cloudways env-capture production -o .env.local  # custom output path
cloudways env-capture production --stdout     # print to stdout
```

### `cloudways ssh`

Open an interactive SSH session or execute commands remotely.

```bash
cloudways ssh production                      # interactive, lands in app directory
cloudways ssh production --server             # interactive, lands at server root
cloudways ssh production -- wp plugin list    # exec mode: run command and return
cloudways ssh production -- wp cache flush    # exec mode: any remote command
```

### `cloudways capistrano`

Generate Capistrano deployment configuration files for Bedrock WordPress projects. Creates `Capfile`, `config/deploy.rb`, per-environment stage files, and `Gemfile`.

```bash
cloudways capistrano                          # generate all config files
cloudways capistrano --with-pipelines         # also generate bitbucket-pipelines.yml
cloudways capistrano --preview                # print to stdout without writing
cloudways capistrano --force                  # overwrite existing files
```

Generated files:

```
Capfile
Gemfile
config/deploy.rb
config/deploy/production.rb
config/deploy/staging.rb
bitbucket-pipelines.yml        (with --with-pipelines)
```

### `cloudways provision server`

Create a new DigitalOcean server on Cloudways. Supports interactive prompts for region, size, and label, or non-interactive mode via flags.

```bash
cloudways provision server                              # interactive prompts
cloudways provision server -r nyc3 -s 2GB -l my-server  # non-interactive
cloudways provision server --from-template server.yml   # from YAML template
cloudways provision server --timeout 900                # custom timeout
```

### `cloudways provision app`

Create a new application on an existing Cloudways server with optional post-creation configuration (PHP version, domain).

```bash
cloudways provision app                                         # interactive prompts
cloudways provision app -s 1234567 -l my-app                    # non-interactive
cloudways provision app --app wordpress --php 8.2 --domain example.com
cloudways provision app --from-template app.yml                 # from YAML template
```

## Configuration

### Credentials (`~/.cloudways/accounts.yml`)

Stores API credentials per account. Values can reference environment variables with `${VAR_NAME}` syntax, resolved from the process environment or `~/.cloudways/.env`.

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

### Project Config (`.prism/project-config.yml`)

Each project stores its hosting configuration under `hosting.cloudways`. The CLI discovers this file by walking up from the current directory (up to 5 levels). Override with the `CLOUDWAYS_PROJECT_CONFIG` environment variable.

Required fields:

| Field | Description |
|-------|-------------|
| `account` | Account name matching `~/.cloudways/accounts.yml` |
| `server.id` | Cloudways server ID (integer) |
| `server.ssh_user` | SSH username (e.g., `master_xxxxxxxxx`) |
| `server.ssh_host` | Server IP address |
| `environments.<name>.app_id` | Cloudways application ID (integer) |
| `environments.<name>.domain` | Primary domain for the environment |
| `database.local_container` | Local Docker MySQL/MariaDB container name |
| `database.local_db_name` | Local database name |
| `database.url_replace_method` | `wp-cli`, `env-file`, or `sql-replace` |

### Provisioning Templates

YAML templates automate server and app provisioning with predefined settings and variable interpolation.

```yaml
provision:
  type: server
  region: nyc3
  size: 2GB
  server_label: "${label}"
  app_label: my-app
  project_name: "${project_name}"
```

CLI flags override template values. Variables use `${name}` syntax, resolved from CLI flags and environment variables.

## Detailed Command Reference

For comprehensive documentation of all 50+ commands with complete flags, options, and examples, see **[CLI-REFERENCE.md](docs/CLI-REFERENCE.md)**.

### Quick Examples by Category

#### Server Lifecycle
```bash
cloudways server stop              # Stop server (waits by default)
cloudways server start             # Start server
cloudways server restart           # Restart server
cloudways server delete --confirm  # Delete server (requires confirmation)
cloudways server rename --label "prod-server"  # Rename server
```

#### SSH & Keys
```bash
cloudways ssh production               # Interactive SSH session
cloudways ssh production -- wp cli version  # Execute remote command
cloudways ssh-key add production --username deploy --key-file ~/.ssh/id_ed25519.pub --name "deploy-key"
cloudways ssh-key delete production --key-id 12345
cloudways ssh-key rename production --key-id 12345 --name "new-name"
```

#### Security & IP Whitelisting
```bash
cloudways security whitelist list           # List SFTP whitelist
cloudways security whitelist list --type mysql  # List MySQL whitelist
cloudways security whitelist add --ip 203.0.113.5
cloudways security whitelist remove --ip 203.0.113.5
cloudways security blacklist-check --ip 203.0.113.5
cloudways security whitelist-siab --ip 203.0.113.5      # Web SSH
cloudways security whitelist-adminer --ip 203.0.113.5   # Database manager
```

#### SSL Certificates
```bash
# Let's Encrypt
cloudways security ssl install production --email admin@example.com --domains example.com,www.example.com
cloudways security ssl renew production
cloudways security ssl auto production --enable
cloudways security ssl revoke production --domain example.com

# Custom certificates
cloudways security ssl install-custom production --cert-file cert.pem --key-file key.pem
cloudways security ssl remove-custom production
```

#### Backup & Disk
```bash
cloudways backup run               # Trigger backup
cloudways backup run --wait        # Wait for completion
cloudways backup settings get      # View backup settings
cloudways backup settings set --frequency 24 --retention 30  # Update settings

cloudways disk settings get        # View disk settings
cloudways disk cleanup --wait      # Clean up disk space
```

#### Git Deployment
```bash
cloudways git clone production --repo https://github.com/user/repo.git --branch main
cloudways git pull production --branch main
cloudways git pull production --branch main --wait
cloudways git branches production --repo https://github.com/user/repo.git
cloudways git history production
```

#### Database Operations
```bash
# Pull database
cloudways db-pull production          # Stream mode (default, faster)
cloudways db-pull production --safe   # File mode (via SFTP)

# Push database
cloudways db-push production          # Push with automatic backup
cloudways db-push production --skip-backup
cloudways db-push production --yes    # Skip confirmation

# Restore from backup
cloudways db-restore production       # Restore latest backup
cloudways db-restore production --list  # List available backups
cloudways db-restore production --backup-file /tmp/backup.sql.gz

# Sync database
cloudways db-sync production          # Bidirectional sync
```

#### Application Management
```bash
cloudways app webroot get production
cloudways app webroot set production --path public_html/current
cloudways services list
cloudways services restart php
cloudways services restart mariadb
cloudways services restart nginx
```

#### Environment Configuration
```bash
cloudways env-capture production          # Capture to .env.production
cloudways env-capture production -o .env.local
cloudways env-capture production --stdout  # Print to stdout
cloudways env-generate                    # Generate from template
```

#### Provisioning
```bash
cloudways provision server                          # Interactive
cloudways provision server -r nyc3 -s 2GB -l prod  # Non-interactive
cloudways provision app                             # Interactive
cloudways provision app -s 1234567 -l my-app --php 8.2
cloudways capistrano --with-pipelines               # Generate deploy config
```

---

## Development

### Prerequisites

- Docker and Docker Compose
- Python 3.13+ (for local development without Docker)

### Running Tests

```bash
# Run all tests (1100+ tests)
docker compose run --rm app python -m pytest tests/ -v

# Run with coverage
docker compose run --rm app python -m pytest tests/ --cov=cloudways_api --cov-report=html

# Run specific test file
docker compose run --rm app python -m pytest tests/test_ssh_key.py -v

# Run with keyword filter
docker compose run --rm app python -m pytest -k "ssl" -v
```

**Test Coverage**: The project includes 1100+ tests covering:
- CLI command argument parsing and validation
- Async Cloudways API client operations
- Database pull/push/sync workflows
- SSH key, user, and deploy key management
- Security and IP whitelisting operations
- SSL certificate lifecycle (Let's Encrypt + custom)
- Backup and disk management
- Git deployment operations
- Server provisioning and lifecycle
- Environment capture and configuration
- Application management and webroot handling

### Linting

```bash
docker compose run --rm app ruff check cloudways_api/ tests/
```

### Project Structure

```
cloudways-api/
├── cloudways_api/
│   ├── __init__.py              # Package version
│   ├── cli.py                   # Typer CLI entry point (50+ commands)
│   ├── client.py                # Async Cloudways API client (httpx)
│   ├── config.py                # Project config loader
│   ├── credentials.py           # Account credential loader
│   ├── db.py                    # Database utilities (mysqldump, import)
│   ├── env_detect.py            # Bedrock vs traditional WordPress detection
│   ├── exceptions.py            # Custom exception hierarchy
│   ├── ssh.py                   # SSH operations (asyncio subprocess)
│   ├── templates.py             # Capistrano template rendering
│   ├── templates_provision.py   # Provisioning template loading/validation
│   ├── url_replace.py           # URL replacement strategies
│   └── commands/
│       ├── _shared.py           # Shared utilities and error handling
│       ├── info.py              # cloudways info
│       ├── db_pull.py           # cloudways db-pull
│       ├── db_push.py           # cloudways db-push
│       ├── db_restore.py        # cloudways db-restore
│       ├── db_sync.py           # cloudways db-sync
│       ├── env_capture.py       # cloudways env-capture
│       ├── env_generate.py      # cloudways env-generate
│       ├── ssh_cmd.py           # cloudways ssh
│       ├── ssh_setup.py         # cloudways ssh-setup
│       ├── ssh_key.py           # cloudways ssh-key (add, delete, rename)
│       ├── ssh_user.py          # cloudways ssh-user (create, list, password, delete)
│       ├── deploy_key.py        # cloudways deploy-key (add, delete)
│       ├── security.py          # cloudways security (whitelist, ssl)
│       ├── server.py            # cloudways server (stop, start, restart, delete, rename)
│       ├── backup.py            # cloudways backup (run, settings)
│       ├── disk.py              # cloudways disk (settings, cleanup)
│       ├── git.py               # cloudways git (clone, pull, branches, history)
│       ├── app_webroot.py       # cloudways app (webroot)
│       ├── services.py          # cloudways services (list, restart)
│       ├── capistrano.py        # cloudways capistrano
│       ├── verify_setup.py      # cloudways verify-setup
│       ├── setup_project.py     # cloudways setup-project
│       ├── setup_bedrock.py     # cloudways setup-bedrock
│       ├── reset_permissions.py # cloudways reset-permissions
│       ├── init_shared.py       # cloudways init-shared
│       └── provision/
│           ├── __init__.py      # Provision sub-command group
│           ├── server.py        # cloudways provision server
│           ├── app.py           # cloudways provision app
│           └── staging.py       # Provision staging configuration
├── docs/
│   └── CLI-REFERENCE.md         # Complete command reference (50+ commands)
├── tests/                       # pytest test suite (1100+ tests)
├── Dockerfile                   # Python 3.13-slim with SSH and MariaDB clients
├── docker-compose.yml           # Development container configuration
├── pyproject.toml               # Package metadata and entry point
├── requirements.txt             # Runtime dependencies
└── requirements-dev.txt         # Development dependencies (pytest, ruff)
```

## License

MIT
