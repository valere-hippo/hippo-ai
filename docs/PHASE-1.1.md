# HIPPO-AI Phase 1.1 — PostgreSQL + User + Role + JWT

## Implemented

- PostgreSQL async connection with SQLAlchemy 2
- `users` table
- User roles:
  - `ADMIN`
  - `MANAGER`
  - `USER`
  - `READ_ONLY`
- Argon2 password hashing through `pwdlib`
- JWT access tokens
- Registration endpoint
- Login endpoint
- Authenticated `/users/me` endpoint
- Alembic initial migration
- Email uniqueness
- Active/inactive user check

## Endpoints

### Register

`POST /api/v1/auth/register`

```json
{
  "email": "user@example.com",
  "full_name": "Example User",
  "password": "change-me-123"
}
```

### Login

`POST /api/v1/auth/login`

```json
{
  "email": "user@example.com",
  "password": "change-me-123"
}
```

Returns:

```json
{
  "access_token": "...",
  "token_type": "bearer"
}
```

### Current user

`GET /api/v1/users/me`

Header:

`Authorization: Bearer <token>`

## First-run migration

After the containers are running:

```bash
docker compose exec api alembic upgrade head
```

Then use Swagger at:

`http://localhost:8000/docs`

## Security notes

- Passwords are never stored in plaintext.
- JWT contains the user ID as `sub`.
- Registration always creates a normal `USER`.
- ADMIN/role elevation will be restricted to an administration workflow in the next security steps.
- Refresh tokens are intentionally not implemented yet; we will define the session strategy before adding them.
