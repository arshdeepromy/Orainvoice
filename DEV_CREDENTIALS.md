# 🔐 Development Credentials

## Default Admin Account

The development environment has been seeded with a default admin account:

```
Email:    admin@orainvoice.com
Password: admin123
Role:     global_admin
```

**Status**: ✅ Verified working

### Login URL
- API: `POST http://localhost:8080/api/v1/auth/login`
- Frontend: http://localhost:3000/login

---

## Demo Org Admin Account

A demo org_admin account with all modules enabled for testing org-level features:

```
Email:    demo@orainvoice.com
Password: demo123
Role:     org_admin
```

- **Organisation**: Demo Workshop
- **Plan**: Demo Plan (private — not shown during registration)
- **Modules**: All 35 modules enabled
- **Auto-sync**: On every app startup, any new modules added to module_registry are automatically enabled for this org

### Seeding
```bash
# Seed both accounts at once
docker compose exec app python scripts/seed_all_dev.py

# Or seed demo org admin only
docker compose exec app python scripts/seed_demo_org_admin.py
```

---

## Account Details

- **Organisation**: OraInvoice Dev Org
- **Plan**: Dev Plan (unlimited features for development)
- **Status**: Active
- **Email Verified**: Yes
- **Permissions**: Full global admin access

---

## Database Access

### PostgreSQL
```
Host:     localhost
Port:     5432
Database: workshoppro
Username: postgres
Password: postgres
```

### Connection String
```
postgresql://postgres:postgres@localhost:5432/workshoppro
```

### Access via Docker
```bash
make db-shell
# or
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres psql -U postgres -d workshoppro
```

---

## Redis Access

```
Host: localhost
Port: 6379
```

### Access via Docker
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec redis redis-cli
```

---

## API Access

### Base URL
```
http://localhost:8080
```

### API Documentation
```
http://localhost:8080/docs (Swagger UI)
http://localhost:8080/redoc (ReDoc)
```

### Health Check
```bash
curl http://localhost:8080/health
```

### Login Example
```bash
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@orainvoice.com",
    "password": "admin123"
  }'
```

---

## Frontend Access

```
http://localhost:3000
```

---

## Re-seeding Admin User

If you need to recreate the admin user:

```bash
# From host
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/seed_dev_user.py

# From inside container
make shell
python scripts/seed_dev_user.py
```

The script is idempotent - it will skip creation if the user already exists.

---

## Security Notes

⚠️ **IMPORTANT**: These are development credentials only!

- **DO NOT** use these credentials in production
- **DO NOT** commit real credentials to version control
- **CHANGE** all default passwords before deploying
- **USE** strong passwords and proper authentication in production
- **ENABLE** MFA for production admin accounts

---

## Additional Test Users

To create additional test users, you can:

1. Use the API at http://localhost:8080/docs
2. Create via the frontend at http://localhost:3000
3. Add custom seed scripts in `scripts/` directory
4. Use SQL directly via `make db-shell`

---

## Environment Variables

All credentials and configuration are stored in `.env` file.

To view current configuration:
```bash
cat .env
```

To update configuration:
```bash
nano .env
# Then restart services
make restart
```

---

## Troubleshooting

### Can't login?
1. Check if user exists:
   ```bash
   make db-shell
   SELECT email, role, is_active FROM users WHERE email = 'admin@orainvoice.com';
   ```

2. Re-run seed script:
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/seed_dev_user.py
   ```

### Forgot to seed?
Run the seed script anytime:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/seed_dev_user.py
```

### Need to reset password?
```bash
make db-shell
# Then in psql:
UPDATE users SET password_hash = '<new_hash>' WHERE email = 'admin@orainvoice.com';
```

Or delete and re-seed:
```bash
make db-shell
DELETE FROM users WHERE email = 'admin@orainvoice.com';
\q
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/seed_dev_user.py
```

---

**Last Updated**: March 9, 2026
**Environment**: Development
**Status**: ✅ Active
