---
name: avgarden-deploy
description: "Deploy AVGARDEN on the NAS from Hermes/Feishu. Use when the user asks to 部署 AVGARDEN, rebuild server/worker, refresh /api/version identity, or apply NAS-local code changes without Mac rsync/sshpass."
version: 1.0.0
metadata:
  hermes:
    tags: [avgarden, deploy, nas, docker, feishu]
    category: devops
    requires_toolsets: [terminal]
---

# AVGARDEN NAS local deploy (Feishu / Hermes)

## When to use

- User is **outside** and talks via **飞书**, asks to deploy / rebuild / restart AVGARDEN
- User edited AVGARDEN sources **on the NAS** (or under the Hermes bind-mount) and wants containers updated
- User wants `/api/version` `tree_hash` refreshed after local NAS edits

## When NOT to use

- User is on the **Mac at home** with the git checkout: use Mac `bash deploy.sh` (rsync + remote build), not this skill
- Never run Mac `deploy.sh` from inside Hermes (needs Mac→NAS rsync / sshpass / AVGARDEN_PASS)

## Paths

| Role | Path |
|------|------|
| Host NAS tree | `/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN` (极空间 `/42/docker/AVGARDEN`) |
| Hermes bind-mount | `/opt/data/projects/AVGARDEN` (same files as host tree) |
| Local API (host network) | `http://127.0.0.1:31471` |
| Containers | `avgarden-server`, `avgarden-worker` |

Prefer the Hermes path when the terminal runs **inside** `hermes-agent`. Use the host path when the shell is already on the NAS host.

## One-shot commands

```bash
# default: rebuild + restart server and worker
bash /opt/data/projects/AVGARDEN/deploy_local.sh

# only Go/Vue server
bash /opt/data/projects/AVGARDEN/deploy_local.sh server

# only Python worker (full image rebuild)
bash /opt/data/projects/AVGARDEN/deploy_local.sh worker

# Python hot patch (no image rebuild) — safe for .py only, not requirements/Dockerfile
AVGARDEN_HOT=1 bash /opt/data/projects/AVGARDEN/deploy_local.sh worker

# after path-specific edits
bash /opt/data/projects/AVGARDEN/deploy_local.sh --paths backend/handlers.go frontend/src/views/HomeView.vue

# only refresh BUILD_INFO into running server (no rebuild)
bash /opt/data/projects/AVGARDEN/deploy_local.sh --identity-only
```

If the bind-mount is missing, fall back to host path (requires host shell / docker.sock access):

```bash
bash /tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN/deploy_local.sh server
```

## Procedure Hermes must follow

1. **Confirm intent** if the user asked something ambiguous (deploy vs only restart vs only logs).
2. **Edit code** under `/opt/data/projects/AVGARDEN` (or host path). Stay inside the project; do not touch `db/`, `.env`, media under `/data`.
3. **Choose scope**
   - Go / Vue / `Dockerfile.server` / `VERSION` → `server`
   - Python / `src/` / `requirements.txt` / `Dockerfile.worker` → `worker`
   - Both / unsure → `all` (default)
   - Tiny worker py fix and user wants speed → `AVGARDEN_HOT=1 … worker`
4. **Run** `deploy_local.sh` with that scope. Builds can take several minutes; stream progress / wait.
5. **Verify**
   ```bash
   curl -fsS http://127.0.0.1:31471/api/version
   curl -fsS http://127.0.0.1:31471/api/queue-status | head -c 400
   docker ps --filter name=avgarden --format '{{.Names}} {{.Status}}'
   ```
   Report `version`, `tree_hash`, `git_sha` (if present), and container `Up` state.
6. **Tell the user about Mac drift**: outside NAS edits make home Mac checkout stale until they pull NAS or re-deploy from Mac. Suggest home: `./check_version.sh`.

## Hard rules

- Do **not** run Mac `deploy.sh` from Hermes.
- Do **not** require `sshpass` or `AVGARDEN_PASS` for local NAS deploy.
- Do **not** `docker image prune -a` or delete unrelated images/containers.
- Do **not** wipe `db/`, `.env`, `cfg/configs.json`, or media library paths.
- Prefer `deploy_local.sh` over hand-rolled long `docker compose` recipes so BUILD_INFO stays consistent.
- If `docker` cannot talk to the daemon, report that `docker.sock` is not mounted into Hermes and ask the operator to fix hermes-agent volumes (see project AGENTS.md).

## Prerequisites (operator once)

`hermes-agent` compose should include:

```yaml
volumes:
  - /tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN:/opt/data/projects/AVGARDEN
  - /var/run/docker.sock:/var/run/docker.sock
```

Without these mounts this skill can only document steps; it cannot build or edit AVGARDEN from inside the container.
