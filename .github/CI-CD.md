# CI/CD pipeline

Defined in [`.github/workflows/ci-cd.yml`](workflows/ci-cd.yml). One workflow, four jobs:

```
push / PR ─▶ backend-tests (pytest, in-memory SQLite) ┐
            frontend-build (tsc --noEmit && vite build)┘─▶ images ─▶ deploy
                                                            │          │
                              PR: build only (validate)  ◀──┘          │
                              main: build + push to GHCR               │
                                                        push to main ◀─┘
```

- **Pull requests** run the tests, the frontend typecheck/build, and a Docker build of
  both images (no push) — so a broken Dockerfile fails the PR.
- **Push to `main`** does all of the above, then pushes `:latest` + `:<sha>` images to
  GHCR, then SSHes into the VM and restarts the stack from the **prebuilt** images
  (`docker compose pull && up -d` — no building on the free-tier VM).

Images: `ghcr.io/seif-walid/mtr_portal-backend` and `…-frontend`.

## Required GitHub secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**.
`GITHUB_TOKEN` is provided automatically (used to push/pull GHCR images).

| Secret | Required | Example / notes |
|---|---|---|
| `VM_HOST` | ✅ | `130.110.17.255` (use the raw IP, not the public hostname) |
| `VM_USER` | ✅ | SSH user on the VM, e.g. `ubuntu` |
| `VM_SSH_KEY` | ✅ | **base64** of the private key whose public half is in the VM's `~/.ssh/authorized_keys` — `base64 -w0 ~/.ssh/your_key` (base64 avoids the trailing-newline mangling that breaks a raw paste) |
| `GOOGLE_CLIENT_SECRET` | ✅ | Google OAuth secret — the prod overlay refuses to start without it |
| `VM_SSH_PORT` | optional | Defaults to `22` |
| `SITE_ADDRESS` | optional | Defaults to `portal.mindtechrobotics.com` |
| `VM_APP_DIR` | optional | Repo path on the VM, defaults to `~/MTR_Portal` |

Generate a deploy key (run locally, add the public half on the VM):

```bash
ssh-keygen -t ed25519 -C "gha-deploy" -f gha_deploy -N ""
# paste gha_deploy.pub into the VM's ~/.ssh/authorized_keys
# put the base64 of the private key into the VM_SSH_KEY secret:
base64 -w0 gha_deploy
```

## One-time VM prep

The deploy job pulls private GHCR images, so the repo clone must already exist on the VM
(the runbook's initial `git clone`) and Docker must be installed. The workflow handles
`docker login ghcr.io` itself each run using `GITHUB_TOKEN`, so no manual login is needed.

## Optional: protect prod

The `deploy` job runs in the `production` GitHub Environment. Add **required reviewers**
there (Settings → Environments → production) to require a manual approval click before any
deploy reaches the VM.

## Manual rollback

Every push is also tagged `:<sha>`. To roll back on the VM:

```bash
cd ~/MTR_Portal
export BACKEND_IMAGE=ghcr.io/seif-walid/mtr_portal-backend:<good-sha>
export FRONTEND_IMAGE=ghcr.io/seif-walid/mtr_portal-frontend:<good-sha>
export SITE_ADDRESS=portal.mindtechrobotics.com GOOGLE_CLIENT_SECRET=…
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
