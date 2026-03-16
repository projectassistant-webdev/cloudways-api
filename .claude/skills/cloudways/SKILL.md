---
name: cloudways
description: Cloudways API operations (db-pull, db-push, db-restore, ssh, provision, etc.) via cloudways-api tool
allowed-tools:
  - Bash
  - Read
tags:
  - cloudways
  - wordpress
  - database
  - hosting
  - operations
  - provisioning
---

# Cloudways Operations Skill

**Status**: Active
**Tool Location**: `tools/cloudways-api/`
**Config Source**: `.prism/project-config.yml` (hosting section)
**Credentials**: `~/.cloudways/accounts.yml`

---

## Docker-First Policy Exception

**The cloudways-api tool is EXEMPT from the Docker-first development policy.**

This tool is a CLI utility that makes HTTP API calls to the Cloudways REST API and SSH connections to remote servers. It does NOT run application code that requires environment consistency. Running it through Docker adds unnecessary complexity (SSH key mounting, permission issues) with zero benefit.

**Run this tool directly with Python on the host:**
```bash
cd tools/cloudways-api
pip install -r requirements.txt  # One-time setup
python -m cloudways_api.cli <command> [args]
```

**Why this exception exists:**
- The Docker-first policy ensures application code runs in consistent environments
- This tool is an external API client, not application code
- Docker mount issues with `~/.ssh` and `~/.cloudways` create friction with no upside
- SSH operations need direct host access to SSH keys

---

## Step 1: Verify Tool Installation

```bash
# Clone if not already installed, pull latest if it is
if [ ! -d "tools/cloudways-api" ]; then
    echo "Installing cloudways-api tool..."
    mkdir -p tools
    git clone https://github.com/projectassistant-webdev/cloudways-api.git tools/cloudways-api
else
    echo "Updating cloudways-api tool..."
    git -C tools/cloudways-api pull origin main --quiet 2>/dev/null || true
fi

# Ensure tools/cloudways-api is gitignored (prevent accidental commit)
if ! grep -q "tools/cloudways-api" .gitignore 2>/dev/null; then
    echo "" >> .gitignore
    echo "# External tools (cloned, not committed)" >> .gitignore
    echo "tools/cloudways-api/" >> .gitignore
fi

# One-time: install Python dependencies (host-side - see Docker-First Policy Exception above)
if ! python3 -c "import typer" 2>/dev/null; then
    pip3 install -r tools/cloudways-api/requirements.txt
fi
```

---

## Step 2: Verify Configuration

The skill requires hosting configuration in `.prism/project-config.yml`:

```yaml
hosting:
  cloudways:
    account: primary
    server:
      id: 12345
      ssh_user: master_xxxxx
      ssh_host: 1.2.3.4
    environments:
      production:
        app_id: 67890
        domain: example.com
        webroot: public_html/current
        branch: main
      staging:
        app_id: 67891
        domain: staging.example.com
        webroot: public_html/current
        branch: staging
    database:
      local_container: mysql
      local_db_name: wordpress_local
      url_replace_method: wp-cli
```

```bash
if ! grep -q "hosting:" .prism/project-config.yml 2>/dev/null; then
    echo "ERROR: Missing hosting configuration in .prism/project-config.yml"
    exit 1
fi
```

---

## Step 3: Run Command

```bash
# Run directly with Python (NOT Docker - see Docker-First Policy Exception)
CLOUDWAYS_PROJECT_CONFIG="$(pwd)/.prism/project-config.yml" \
  python3 -m cloudways_api.cli $COMMAND $ENVIRONMENT
```

Run from `tools/cloudways-api/` directory, or set `PYTHONPATH` accordingly.

---

## Credentials Setup

### accounts.yml

```yaml
# ~/.cloudways/accounts.yml
accounts:
  primary:
    email: "your@email.com"
    api_key: "${CLOUDWAYS_API_KEY}"
```

API keys reference environment variables with `${VAR_NAME}` syntax. Store actual keys in `~/.cloudways/.env`:
```bash
CLOUDWAYS_API_KEY=your-actual-api-key-here
```

---

## Command Reference

### Server Management

```bash
cloudways info [ENVIRONMENT]              # Show server & app details
cloudways server start [--timeout 300]    # Start server
cloudways server stop [--timeout 300]     # Stop server
cloudways server restart [--timeout 300]  # Restart server
cloudways server delete --confirm         # Delete server (DANGEROUS)
cloudways server rename --label "Name"    # Rename server
```

### Database Operations

```bash
cloudways db-pull production              # Pull remote DB to local Docker
cloudways db-pull staging --safe          # File mode (reliable for large DBs)
cloudways db-push staging                 # Push local DB to remote
cloudways db-push production --yes        # Skip production confirmation
cloudways db-sync production staging      # Copy prod DB to staging
cloudways db-restore staging              # Restore latest backup
cloudways db-restore staging --list       # List available backups
```

### Environment Configuration

```bash
cloudways env-capture production          # Capture remote .env
cloudways env-generate production         # Generate and deploy Bedrock .env
cloudways env-generate staging --output .env.staging  # Write locally
```

### Git Deployment

```bash
cloudways git clone staging --repo git@bitbucket.org:org/repo.git --branch main
cloudways git pull staging --branch staging --wait
cloudways git branches staging --repo git@bitbucket.org:org/repo.git
cloudways git history staging
```

### Backup Management

```bash
cloudways backup run --wait
cloudways backup settings get
cloudways backup settings set --frequency 24 --retention 7 --time 00:10
```

### SSH Access

```bash
cloudways ssh production                  # Interactive SSH to app directory
cloudways ssh staging --server            # SSH to server root
cloudways ssh production -- wp plugin list  # Run remote command
cloudways ssh-setup                       # First-time SSH configuration
```

### SSH Key & User Management

```bash
cloudways ssh-key list / add / delete
cloudways ssh-user list / add / delete / reset-password
```

### Security & SSL

```bash
# IP Whitelisting
cloudways security whitelist list [--type ip|cidr|country]
cloudways security whitelist add ENVIRONMENT --ip IP --type ip|cidr
cloudways security whitelist remove RULE_ID
cloudways security blacklist-check --ip IP
cloudways security whitelist-siab --ip IP
cloudways security whitelist-adminer --ip IP

# SSL Certificate Management (subgroup under security)
cloudways security ssl install ENVIRONMENT --email EMAIL --domains DOMAINS [--wildcard]
cloudways security ssl renew ENVIRONMENT [--wildcard] [--email EMAIL] [--domain DOMAIN]
cloudways security ssl auto ENVIRONMENT --enable|--disable
cloudways security ssl revoke ENVIRONMENT --domain DOMAIN [--wildcard]
cloudways security ssl install-custom ENVIRONMENT --cert-file PATH --key-file PATH
cloudways security ssl remove-custom ENVIRONMENT
```

### Alerts & Notifications

```bash
cloudways alerts list / read ALERT_ID / read-all
cloudways alerts channels list / available / add / update / delete
```

### Cloudflare Analytics

```bash
cloudways cloudflare analytics ENVIRONMENT --mins 60
cloudways cloudflare security ENVIRONMENT --mins 60
cloudways cloudflare logpush ENVIRONMENT --type analytics|security
```

### Copilot Management

```bash
cloudways copilot plans / status / subscribe / cancel / change-plan / billing
cloudways copilot server-settings / enable-insights / disable-insights / insights / insight
```

### SafeUpdate Management

```bash
cloudways safeupdates check / list / status / enable / disable
cloudways safeupdates settings get / set --day monday --time 02:00
cloudways safeupdates run ENVIRONMENT --core --plugin a,b --theme x
cloudways safeupdates schedule / history
```

### Monitoring & Analytics

```bash
cloudways monitor server-summary --type bandwidth|disk
cloudways monitor server-usage --wait
cloudways monitor server-graph --target cpu --duration 1h --format json|svg
cloudways monitor app-summary ENVIRONMENT --type bw|db
cloudways monitor traffic ENVIRONMENT --duration 1d --resource top_ips --wait
cloudways monitor traffic-details ENVIRONMENT --from 2026-03-01 --until 2026-03-15
cloudways monitor php / mysql / cron ENVIRONMENT --duration 1h --resource <type> --wait
```

### App Security Suite (Imunify360)

```bash
cloudways appsec status / scan --wait / scan-status / scans / scan-detail
cloudways appsec files / restore --files a.php,b.php / diff
cloudways appsec events / incidents
cloudways appsec activate / deactivate
cloudways appsec ip-add --ip 1.2.3.4 --mode block / ip-remove --ip 1.2.3.4
```

### Server Security Suite

```bash
cloudways serversec incidents
cloudways serversec ips list / add --ip 1.2.3.4 --mode block --ttl 24 --ttl-type hours / remove
cloudways serversec geoblock add --country CN / remove --country CN
cloudways serversec stats --start 2026-03-01 --end 2026-03-15 --group-by day
cloudways serversec infected-domains / sync-domains
cloudways serversec firewall get / set --request-limit 100 --weak-password
cloudways serversec apps --filter-by infected --page 1
```

### Team Member Management

```bash
cloudways team list / add --email user@example.com / update MEMBER_ID / remove MEMBER_ID
```

### Provisioning

```bash
cloudways provision server --provider do --size 1GB --region nyc1 --label "My Server"
cloudways provision app ENVIRONMENT --label "My App" --project "WordPress"
cloudways provision staging --source production --label "Staging"
```

### Project Setup & Utilities

```bash
cloudways setup-project            # Interactive project wizard
cloudways setup-bedrock            # Configure Bedrock WordPress
cloudways init-shared ENVIRONMENT  # Create shared directory structure
cloudways verify-setup             # Validate config and SSH connectivity
cloudways reset-permissions        # Fix file permissions on remote
cloudways capistrano               # Generate Capistrano config
cloudways deploy-key list / add / delete
cloudways disk cleanup --wait              # Clean up server disk
cloudways disk settings get / set          # Disk alert thresholds
cloudways services deploy ENVIRONMENT      # Deploy/restart services
```

---

## Common Workflows

### New WordPress Site Setup

```bash
cloudways provision server --provider do --size 2GB --region nyc1 --label "Client Server"
cloudways provision app production --label "client-site" --project "WordPress"
cloudways setup-project
cloudways ssh-setup
cloudways verify-setup
cloudways capistrano --with-pipelines
cloudways init-shared production
cloudways env-generate production
cloudways git clone production --repo git@bitbucket.org:org/repo.git --branch main
```

### Database Sync (Production to Local)

```bash
cloudways db-pull production  # Auto-replaces prod URLs with localhost
```

### Database Sync (Production to Staging)

```bash
cloudways db-sync production staging  # Auto-backup + URL replacement
```

### Security Audit

```bash
cloudways appsec status production
cloudways appsec scan production --wait
cloudways serversec incidents
cloudways serversec firewall get
```

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CLOUDWAYS_PROJECT_CONFIG` | Path to project config | `.prism/project-config.yml` |
| `CLOUDWAYS_ACCOUNTS_FILE` | Path to credentials | `~/.cloudways/accounts.yml` |
| `CLOUDWAYS_EMAIL` | Fallback API email | — |
| `CLOUDWAYS_API_KEY` | Fallback API key | — |

---

**Full reference for configuration schema, command details, and troubleshooting**: See `.claude/reference/deploy-cloudways-reference.md`

**Last Updated**: 2026-03-16
