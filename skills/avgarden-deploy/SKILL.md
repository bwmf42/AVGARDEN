---
name: avgarden-deploy
description: "Deploy AVGARDEN on the NAS from Hermes/Feishu using the fastest safe path (HOT worker / server-only / path classify). Use when the user asks to 部署 AVGARDEN, rebuild, 热更新, or apply NAS-local code changes without Mac rsync/sshpass."
version: 1.1.0
metadata:
  hermes:
    tags: [avgarden, deploy, nas, docker, feishu, hot]
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
| Deploy script | `/opt/data/projects/AVGARDEN/deploy_local.sh` |

Prefer the Hermes path when the terminal runs **inside** `hermes-agent`.

## Default: fastest safe path (required)

**Do not** default to bare `bash deploy_local.sh` (that rebuilds server+worker — slowest).

After edits, pick the **fastest safe** command using the decision tree below. State in the reply which tier you chose and why (1–2 lines).

### Decision tree (fast → slow)

1. **Identity / docs only** (only `BUILD_INFO.json`, `*.md`, `docs/`, skill text, no runtime code)  
   → `bash deploy_local.sh --identity-only`  
   or skip deploy if nothing runtime-facing changed.

2. **Worker Python only** — changed paths are subset of:
   - root `*.py` (e.g. `worker.py`, `queue_api.py`, `launcher.py`, …)
   - `src/**`
   - `tools/maintenance/**`
   - and **none** of: `requirements.txt`, `Dockerfile.worker`, `Dockerfile.server`, `backend/**`, `frontend/**`, `docker-compose.yml`  
   → **HOT (default fastest for py):**
   ```bash
   AVGARDEN_HOT=1 bash /opt/data/projects/AVGARDEN/deploy_local.sh worker
   ```
   If HOT fails (container missing, cp error) → fall back to full worker image:
   ```bash
   bash /opt/data/projects/AVGARDEN/deploy_local.sh worker
   ```

3. **Server only** — only `backend/**`, `frontend/**`, `Dockerfile.server`, `VERSION` (no worker py / requirements / Dockerfile.worker)  
   →
   ```bash
   bash /opt/data/projects/AVGARDEN/deploy_local.sh server
   ```

4. **Worker image inputs changed** — any of `requirements.txt`, `Dockerfile.worker`  
   → full worker build (**never HOT**):
   ```bash
   bash /opt/data/projects/AVGARDEN/deploy_local.sh worker
   ```

5. **Both sides or unclear** — server + worker inputs, or you cannot list changed paths  
   →
   ```bash
   bash /opt/data/projects/AVGARDEN/deploy_local.sh all
   ```
   Explain why HOT/server-only was not used.

### Path-classified form (when you know exact files)

Same as Mac `deploy.sh` classify — prefer when you edited a known set:

```bash
bash /opt/data/projects/AVGARDEN/deploy_local.sh --paths worker.py queue_api.py
# or with HOT when all paths are HOT-eligible py:
AVGARDEN_HOT=1 bash /opt/data/projects/AVGARDEN/deploy_local.sh --paths worker.py src/foo.py
```

Note: `--paths` still needs `AVGARDEN_HOT=1` for hot worker; without it worker gets a full image build.

### Command cheat sheet

| Intent | Command |
|--------|---------|
| Fastest py patch | `AVGARDEN_HOT=1 bash …/deploy_local.sh worker` |
| Server only | `bash …/deploy_local.sh server` |
| Worker image rebuild | `bash …/deploy_local.sh worker` |
| Both (last resort) | `bash …/deploy_local.sh all` |
| Identity only | `bash …/deploy_local.sh --identity-only` |
| Classify by paths | `bash …/deploy_local.sh --paths <files…>` (+ `AVGARDEN_HOT=1` if py-only) |

If bind-mount missing, use host path:

```bash
bash /tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN/deploy_local.sh …
```

## Procedure Hermes must follow

1. **Confirm intent** only if ambiguous (deploy vs logs-only vs rollback).
2. **Edit** under `/opt/data/projects/AVGARDEN`. Never touch `db/`, `.env`, media under `/data`.
3. **List changed paths** from this turn (or `find`/mtime if user said “deploy current tree” without a list).
4. **Apply decision tree** → run **one** `deploy_local.sh` invocation (HOT preferred when eligible).
5. **Verify**
   ```bash
   curl -fsS http://127.0.0.1:31471/api/version
   curl -fsS http://127.0.0.1:31471/api/queue-status | head -c 400
   docker ps --filter name=avgarden --format '{{.Names}} {{.Status}}'
   ```
   Report: tier chosen, `version`, `tree_hash`, `git_sha` (if any), containers `Up`.
6. **Mac drift**: NAS edits stale the home checkout. Tell user to run `./check_version.sh` at home before the next Mac deploy.

## Hard rules

- Do **not** run Mac `deploy.sh` from Hermes.
- Do **not** require `sshpass` or `AVGARDEN_PASS` for local NAS deploy.
- Do **not** default to full `all` when a narrower tier fits.
- Do **not** use HOT if `requirements.txt` or any `Dockerfile*` changed.
- Do **not** `docker image prune -a` or delete unrelated images/containers.
- Do **not** wipe `db/`, `.env`, `cfg/configs.json`, or media library paths.
- Prefer `deploy_local.sh` over hand-rolled long `docker compose` recipes so BUILD_INFO stays consistent.
- If `docker` cannot talk to the daemon, report that `docker.sock` is not mounted into Hermes.

## Prerequisites (operator once)

`hermes-agent` compose should include:

```yaml
volumes:
  - /tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN:/opt/data/projects/AVGARDEN
  - /var/run/docker.sock:/var/run/docker.sock
```

Without these mounts this skill can only document steps; it cannot build or edit AVGARDEN from inside the container.
