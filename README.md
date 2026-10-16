# assistant-mcp

Modularer MCP-Server auf Basis von [FastMCP](https://gofastmcp.com/), deploybar auf Google Cloud Run
(Target-Projekt: `rubenschulze-sandbox`).

## Struktur

```
src/assistant_mcp/
├── server.py        # Einstiegspunkt: FastMCP-Server, mountet alle Toolsets
├── toolsets/
│   ├── __init__.py  # Toolset-Registry
│   └── pdf.py       # PDF-Toolset: Markdown-to-PDF und Office-to-PDF
└── ...
```

Jedes Toolset ist ein eigenes Modul mit einer FastMCP-Instanz; neue Toolsets werden in
`toolsets/__init__.py` registriert und automatisch vom Server gemountet. Das PDF-Toolset
dient dabei als Referenzimplementierung.

## Lokale Entwicklung

Benötigt Python 3.14 (`requires-python >= 3.14`, per `.python-version` gepinnt).

```bash
uv sync
uv run assistant-mcp           # stdio-Transport (z. B. für lokale MCP-Clients)
uv run pytest                  # Tests
uv run ruff check .            # Lint
uv run mypy src                # Typ-Check
```

## CI

`.github/workflows/ci.yml` läuft für jeden Pull Request gegen `main`, jeden Push auf
`main` und auf manuelle Auslösung (`workflow_dispatch`):

- **host**: `ruff`, `mypy` und `pytest` auf Python 3.14 (via `setup-uv`, Cache aktiv).
- **docker**: Baut das Container-Image und führt die komplette Testsuite *im Image*
  aus — so laufen auch die `soffice`-gated Office-to-PDF-Tests wirklich (auf dem
  Runner ohne LibreOffice wären sie Skips).

Pull-Requests veröffentlichen das Image nicht; gepusht wird ausschließlich im
Deploy-Pipeline auf `main`.

## Deployment auf Cloud Run

`.github/workflows/deploy.yml` deployt automatisch bei jedem Push auf `main` und per
manueller Auslösung (`workflow_dispatch`):

1. Verifikation des Commits (host-Checks und In-Image-Tests, identisch zu CI).
2. WIF-Authentifizierung (GitHub-OIDC, kein Service-Account-Key in GitHub).
3. Image-Build und Push nach Artifact Registry:
   `europe-west1-docker.pkg.dev/rubenschulze-sandbox/assistant-mcp/server`.
4. Deploy des digest-gepinnten Images auf den Service `assistant-mcp` (Region
   `europe-west1`, `MCP_TRANSPORT=http`, unauthentifizierter Zugriff erlaubt).

Deployen nur nach grüner Verifikation desselben Commits. Rollback: `workflow_dispatch`
auf dem letzten guten Commit oder `gcloud run services update-traffic` auf die
vorherige Revision.

Abhängigkeiten werden von [Dependabot](https://github.com/dependabot) überwacht
(`pip`, `github-actions`, `docker`, wöchentlich). Patch- und Minor-Updates mergen per
Auto-Merge, sobald CI grün ist; Major-Updates bleiben für manuelles Review offen.

## Einmalige Einrichtung

Die Pipeline setzt diese GCP-Ressourcen voraus (Einmal-Aufbau, danach wartungsfrei):

```bash
# Artifact Registry Repository
gcloud artifacts repositories create assistant-mcp \
  --repository-format=docker --location=europe-west1 --project=rubenschulze-sandbox

# Workload Identity Pool + OIDC-Provider (auf dieses Repo beschränkt)
gcloud iam workload-identity-pools create github-actions \
  --location=global --project=rubenschulze-sandbox --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github-com \
  --location=global --workload-identity-pool=github-actions \
  --project=rubenschulze-sandbox \
  --issuer="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '5pirit5eal/assistant-mcp'"

# Deploy-Service-Account
gcloud iam service-accounts create github-actions-deploy \
  --project=rubenschulze-sandbox --display-name="GitHub Actions deploy"

# Rollen (Bild schreiben, Service deployen, Runtime-SA nutzen dürfen)
gcloud artifacts repositories add-iam-policy-binding assistant-mcp \
  --location=europe-west1 --project=rubenschulze-sandbox \
  --member="serviceAccount:github-actions-deploy@rubenschulze-sandbox.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud run services add-iam-policy-binding assistant-mcp \
  --region=europe-west1 --project=rubenschulze-sandbox \
  --member="serviceAccount:github-actions-deploy@rubenschulze-sandbox.iam.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud iam service-accounts add-iam-policy-binding \
  $(gcloud projects describe rubenschulze-sandbox --format='value(projectNumber)')-compute@developer.gserviceaccount.com \
  --project=rubenschulze-sandbox \
  --member="serviceAccount:github-actions-deploy@rubenschulze-sandbox.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

# Provider darf den Deploy-Account impersonieren
gcloud iam service-accounts add-iam-policy-binding \
  github-actions-deploy@rubenschulze-sandbox.iam.gserviceaccount.com \
  --project=rubenschulze-sandbox \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$(gcloud projects describe rubenschulze-sandbox --format='value(projectNumber)')/locations/global/workloadIdentityPools/github-actions/attribute.repository/5pirit5eal/assistant-mcp"
```

Danach die Provider-Ressource (enthält die Projektnummer) als GitHub-Repository-Variable
hinterlegen — der Workflow liest sie als `vars.WORKLOAD_IDENTITY_PROVIDER`:

```bash
gh variable set WORKLOAD_IDENTITY_PROVIDER \
  --repo 5pirit5eal/assistant-mcp \
  --body "projects/$(gcloud projects describe rubenschulze-sandbox --format='value(projectNumber)')/locations/global/workloadIdentityPools/github-actions/providers/github-com"
```

Zusätzlich einmalig auf GitHub: Branch-Protection für `main` aktivieren — die Checks
des `ci`-Workflows als Required Checks festlegen, direkte Pushes blockieren, Auto-Merge
erlauben (macht auch das Dependabot-Auto-Merge erst wirksam).

Der Server lauscht auf `$PORT` (Cloud Run Standard) und nutzt standardmäßig den
Streamable-HTTP-Transport von FastMCP unter `/mcp`.
