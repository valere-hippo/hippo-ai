# HIPPO-AI Phase 1

## Scope

### Foundation
- [x] Docker Compose
- [x] FastAPI API
- [x] PostgreSQL
- [x] Redis
- [x] Environment configuration
- [x] Health/readiness endpoints
- [ ] Alembic initial migration
- [ ] User model
- [ ] Role model
- [ ] JWT login
- [ ] Refresh token strategy
- [ ] Project model
- [ ] Project membership/permissions
- [ ] Audit log

## Planned roles

- ADMIN
- MANAGER
- USER
- READ_ONLY

## Project permissions

- READ
- WRITE
- CREATE
- DELETE (disabled by default)

## Security principle

A project folder is never accessible to the AI merely because a user can chat.
The user must explicitly authorize a project connector and its permissions.
