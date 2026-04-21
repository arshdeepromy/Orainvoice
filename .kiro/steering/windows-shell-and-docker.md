---
inclusion: auto
---

# Windows Development Environment — Shell & Docker Reference

This workspace runs on **Windows** with **PowerShell** as the default shell. All terminal commands must use PowerShell syntax. Bash syntax will silently fail or produce confusing errors.

## Shell Rules

### PowerShell — Use These
- Command separator: `;` (semicolon)
- Output to string: `| Out-String`
- Write output: `Write-Host "message"`
- Suppress errors: `2>$null` or `-ErrorAction SilentlyContinue`
- Environment variables: `$env:VAR_NAME`
- Multiline commands: backtick `` ` `` at end of line

### Bash — Do NOT Use These
- `&&` chaining — **breaks in PowerShell** with `The token '&&' is not a valid statement separator`
- `2>&1` redirection — behaves inconsistently, often produces `NativeCommandError`
- `$VARIABLE` — use `$env:VARIABLE` instead
- `export VAR=value` — use `$env:VAR = "value"` instead
- `echo` — works but prefer `Write-Host` for reliability
- `||` — use `try/catch` or `; if ($LASTEXITCODE -ne 0) { ... }` instead

## Docker Compose

### Project Name
The local dev containers use project name **`orainvoice`** (not derived from the workspace folder name `Invoicing`). Always specify `-p orainvoice` when the compose files are not picking up containers automatically.

### Compose File Selection
The `.env` file sets `COMPOSE_FILE=docker-compose.yml;docker-compose.dev.yml`. If compose commands don't find containers, specify files explicitly:
```powershell
docker compose -p orainvoice -f docker-compose.yml -f docker-compose.dev.yml <command>
```

### Common Docker Commands (PowerShell)
```powershell
# Check running containers
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Stop and remove containers (preserves data volumes)
docker compose -p orainvoice -f docker-compose.yml -f docker-compose.dev.yml down

# Rebuild and restart everything (preserves pgdata + redisdata)
docker compose -p orainvoice -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate

# Delete frontend_dist volume for fresh frontend rebuild
docker volume rm orainvoice_frontend_dist

# Check volumes
docker volume ls --format "{{.Name}}" | Select-String orainvoice

# View container logs
docker logs orainvoice-app-1 --tail 50
docker logs orainvoice-postgres-1 --tail 50
```

### Data Volumes — Never Delete These
- `orainvoice_pgdata` — PostgreSQL database (all org/customer/invoice data)
- `orainvoice_redisdata` — Redis cache

### Safe to Delete & Rebuild
- `orainvoice_frontend_dist` — rebuilt automatically on `up --build`

## Tool Preferences

When running commands from Kiro:
- Use `controlPwshProcess` (background process) for docker commands — gives cleaner output and handles long-running builds
- Use `getProcessOutput` to monitor build progress
- Avoid `executePwsh` for docker compose commands — output is often garbled with PowerShell echo artifacts
- For quick checks (docker ps, volume ls), either tool works

## Port Mappings (Local Dev)
| Service  | Host Port | Container Port |
|----------|-----------|----------------|
| nginx    | 80        | 80             |
| postgres | 5434      | 5432           |
| redis    | 6379      | 6379           |
| app      | (internal)| 8000           |
