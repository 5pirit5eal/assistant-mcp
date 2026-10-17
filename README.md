# assistant-mcp

Modularer MCP-Server auf Basis von [FastMCP](https://gofastmcp.com/), deploybar auf Google Cloud Run
(Target-Projekt: `rubenschulze-sandbox`).

## Struktur

```
src/assistant_mcp/
├── server.py        # Einstiegspunkt: FastMCP-Server, mountet alle Toolsets
├── toolsets/
│   ├── __init__.py  # Toolset-Registry
│   ├── nextcloud.py # Nextcloud-Toolset: Bilder-Listing und -Download über WebDAV
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
   `europe-west1`, `MCP_TRANSPORT=http`, unauthentifizierter Zugriff erlaubt)
   — inklusive OAuth-Konfiguration: `MCP_BASE_URL` (Service-URL) und
   `MCP_ALLOWED_EMAILS` als plain Env-Vars, `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET` und `MCP_OAUTH_STORAGE_KEY` per `--set-secrets` aus
   Secret Manager (siehe „Authentifizierung“); dazu `MCP_STATELESS_HTTP=true` und
   einen Startup-Probe auf `/healthz` (siehe „Startup-Probe und stateless HTTP“).

### Startup-Probe und stateless HTTP

Der Deploy konfiguriert einen Startup-Probe auf `GET /healthz` (Container-Port 8080,
Budget 60 s für den Python-Kaltstart). Solange der Probe einer frischen Instanz noch
nicht erfolgreich war, hält Cloud Run eingehende Requests zurück, statt sie an die
noch nicht bereite Instanz zu routen — der Client sieht eine verzögerte, aber
erfolgreiche Antwort statt einer Fehlerantwort. Der Deploy-Health-Check verweigert
zudem das Rollout einer Revision, deren Startup-Probe nicht erfolgreich ist; die
bisherige Revision bleibt erreichbar. Der Endpoint ist ohne Authentifizierung
erreichbar und prüft absichtlich keine Abhängigkeiten (kein Firestore-Ping).

Der HTTP-Transport läuft stateless: Jeder Request wird unabhängig bedient, es wird
kein Session-State im Prozess gehalten. In diesem Modus bedient der MCP-Endpoint
keinen GET-Server-Initiated-Stream mehr (Clients nutzen POST); der lokale
stdio-Transport ist von der Variable unberührt. Persistenter State
(OAuth-Registrierungen und Token-Datensätze) liegt verschlüsselt in Firestore;
Lesezugriffe werden prozesslokal gecacht — nur mit Ciphertext, TTL 5 Minuten,
Schreibzugriffe invalidieren den Cache-Eintrag und persistieren.

| Variable | Bedeutung | Injektion im Deploy |
|---|---|---|
| `MCP_STATELESS_HTTP` | `false` (case-insensitive) stellt stateful HTTP wieder her; ungesetzt oder jeder andere Wert: stateless (Default) | Plain Env Var (`true`, Deploy-Workflow) |

Deployen nur nach grüner Verifikation desselben Commits. Rollback: `workflow_dispatch`
auf dem letzten guten Commit oder `gcloud run services update-traffic` auf die
vorherige Revision.

Abhängigkeiten werden von [Dependabot](https://github.com/dependabot) überwacht
(`uv`, `github-actions`, `docker`, wöchentlich). Patch- und Minor-Updates mergen per
Auto-Merge, sobald CI grün ist; Major-Updates bleiben für manuelles Review offen.

## Authentifizierung (Google OAuth 2.1)

Der öffentlich erreichbare HTTP-Service verlangt für jeden Request ein gültiges
OAuth-2.1-Token: Authorization-Code-Flow mit PKCE, Google als Identity Provider,
dynamische Client-Registrierung; die Tokens stellt der Service selbst (FastMCP)
aus. Ein App-Layer-Allowlist begrenzt den Zugriff auf explizit konfigurierte
Google-Accounts: Wer sich bei Google authentifiziert, aber nicht auf der Allowlist
steht, erhält kein brauchbares Token. Der OAuth-State (Client-Registrierungen und
Token-Datensätze) liegt verschlüsselt in Firestore und überlebt Neustarts und
Cold Starts. Der stdio-Transport (lokal) bleibt vollständig ohne Auth.

**Aktivierungs-Kontrakt:** Die Auth aktiviert sich nur, wenn **alle** fünf
Konfigurationswerte gesetzt sind. Ohne alle fünf startet der Server ohne
Authentifizierung; bei einer Teilmenge verweigert er den Start und nennt die
fehlenden Variablen.

| Variable | Bedeutung | Injektion im Deploy |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Google-OAuth-Client-ID | Secret Manager (`google-client-id`) |
| `GOOGLE_CLIENT_SECRET` | Google-OAuth-Client-Secret | Secret Manager (`google-client-secret`) |
| `MCP_BASE_URL` | Öffentliche Service-URL, absolut mit `https://` | Plain Env Var (löst der Workflow per `gcloud run services describe` auf) |
| `MCP_ALLOWED_EMAILS` | Komma-separierte Allowlist, Match Case-insensitive | Plain Env Var (GitHub-Variable `MCP_ALLOWED_EMAILS`) |
| `MCP_OAUTH_STORAGE_KEY` | Fernet-Key zur Verschlüsselung des OAuth-State | Secret Manager (`mcp-oauth-storage-key`) |

### Einmalige Google-Cloud-Einrichtung

1. **OAuth-Consent-Screen** anlegen (Konsole → APIs & Services → OAuth consent
   screen, Typ *External*, App-Name und Support-Email setzen).
2. **OAuth-Client** (Konsole → APIs & Services → Credentials → *Create OAuth
   client ID*, Typ *Web application*) mit der Redirect-URI
   `https://<service-url>/auth/callback`:

   ```bash
   gcloud run services describe assistant-mcp \
     --region=europe-west1 --project=rubenschulze-sandbox \
     --format='value(status.url)'
   ```

3. **Drei Secret-Manager-Secrets** anlegen. Client-ID/Secret aus Schritt 2
   einsetzen; der Storage-Key ist ein frisch generierter Fernet-Key:

   ```bash
   echo -n "<client-id>" | \
     gcloud secrets create google-client-id --project=rubenschulze-sandbox --data-file=-
   echo -n "<client-secret>" | \
     gcloud secrets create google-client-secret --project=rubenschulze-sandbox --data-file=-
   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" | \
     gcloud secrets create mcp-oauth-storage-key --project=rubenschulze-sandbox --data-file=-
   ```

4. **Deploy-Service-Account** darf die drei Secrets lesen:

   ```bash
   for secret in google-client-id google-client-secret mcp-oauth-storage-key; do
     gcloud secrets add-iam-policy-binding "$secret" --project=rubenschulze-sandbox \
       --member="serviceAccount:github-actions-deploy@rubenschulze-sandbox.iam.gserviceaccount.com" \
       --role="roles/secretmanager.secretAccessor"
   done
   ```

5. **Firestore** (Native Mode) aktivieren und dem Runtime-Service-Account
   Zugriff geben. Der Server nutzt explizit die **`(default)`-Datenbank** —
   der Firestore-Free-Tier gilt nur für sie, nicht für benannte Datenbanken:

   ```bash
   gcloud firestore databases create \
     --project=rubenschulze-sandbox --location=europe-west2 --type=firestore-native

   gcloud projects add-iam-policy-binding rubenschulze-sandbox \
     --member="serviceAccount:assistant-mcp-runtime@rubenschulze-sandbox.iam.gserviceaccount.com" \
     --role="roles/datastore.user"
   ```

   Der OAuth-State ist so klein (Client-Registrierungen und Token-Datensätze
   einer Person), dass der Free-Tier (u. a. 50k Lese- und 20k
   Schreiboperationen pro Tag) locker ausreicht.

6. **Allowlist als GitHub-Repository-Variable** hinterlegen (der Workflow liest
   sie als `vars.MCP_ALLOWED_EMAILS` und bricht mit einer Fehlermeldung ab,
   wenn sie fehlt):

   ```bash
   gh variable set MCP_ALLOWED_EMAILS \
     --repo 5pirit5eal/assistant-mcp \
     --body "you@example.com,other@example.com"
   ```

### MCP-Clients: Verbinden und Einloggen

Der MCP-Endpoint ist `https://<service-url>/mcp`. OAuth-fähige Clients entdecken
die Metadaten unter `/.well-known/oauth-protected-resource/mcp`, öffnen für die
Autorisierung den Browser (Google-Login, Consent) und erhalten danach ein Token.
Mit FastMCP:

```python
from fastmcp import Client

async with Client("https://<service-url>/mcp", auth="oauth") as client:
    tools = await client.list_tools()
```

Nur Google-Accounts von `MCP_ALLOWED_EMAILS` erhalten ein brauchbares Token.

### Manuelle Verifikation nach dem Deploy

- [ ] Browser-Login mit einem Allowlist-Account gelingt (Consent → Token) und
      ein Tool-Call (z. B. `pdf_generate_pdf`) funktioniert.
- [ ] Unauthentifizierte Requests werden abgelehnt:
      `curl -i https://<service-url>/mcp` → `401`.
- [ ] Der Login überlebt einen Neustart: neuen Deploy anstoßen (z. B. Workflow
      manuell auf `main` auslösen) — der Client muss danach ohne erneuten Login
      weiterarbeiten, weil der OAuth-State aus Firestore kommt.

### Schlüssel-Rotation (`MCP_OAUTH_STORAGE_KEY`)

Rotation: neuen Fernet-Key ins Secret schreiben → neue Revision. Alte Einträge
lassen sich dann nicht mehr entschlüsseln und werden als *fehlend* behandelt:
Clients müssen sich neu registrieren und neu einloggen. Token-Material wird nie
im Klartext exponiert — niemals durch die Rotation, auch nicht im Fehlerfall.

## Nextcloud-Toolset (Bilder über WebDAV)

Das `nextcloud`-Toolset greift per WebDAV auf die Bilder eines Nextcloud-Kontos zu
(z. B. Hetzner Storage Share) und mountet drei Tools unter dem Namespace `nextcloud`:

- `nextcloud_register_nextcloud_credentials` — validiert und speichert die WebDAV-Zugangsdaten
  des Aufrufers (Validation vor Persistenz: abgelehnte Zugangsdaten werden nicht gespeichert).
- `nextcloud_list_images` — listet in einem Pfad die Bilddateien und Unterordner auf,
  mit den WebDAV-Metadaten je Eintrag (Name, Pfad, Content-Type, Größe, Datei-ID,
  Änderungsdatum, Berechtigungen, Besitzer, `has_preview`). Für jede Bilddatei mit
  verfügbarer Vorschau liefert das Ergebnis zusätzlich ein 256×256-Thumbnail als
  Image-Content-Block — das k-te Thumbnail gehört zum k-ten Eintrag mit
  `has_preview = true`. Fehlt eine Vorschau oder schlägt ihr Abruf fehl, wird der
  Eintrag ohne Thumbnail zurückgegeben (`has_preview = false`); die Liste scheitert
  daran nie. Dateien über eingehängte Freigaben (mounted shares) werden wie eigene
  gelistet. Filter: `bmp, gif, heic, jpeg, jpg, png, tif, tiff, webp` plus alle Ordner.
- `nextcloud_download_image` — lädt eine Bilddatei unverändert herunter und liefert
  sie als Bild-Ergebnis (Image-Content) mit dem Bild-Media-Type zurück, damit das
  Modell sie direkt ansehen kann.

### Zugangsdaten pro Benutzer (identitätsbasiert)

Jede authentifizierte Person speichert ihre eigenen Nextcloud-Zugangsdaten über
`nextcloud_register_nextcloud_credentials`:

1. **App-Passwort erzeugen** (Hetzner Storage Share): Nextcloud-Web-UI öffnen →
   *Einstellungen → Sicherheit* → unter „Geräte & Sitzungen“ ein neues App-Passwort
   erstellen (Name z. B. „assistant-mcp“). Das App-Passwort nur einmalig kopiert
   anzeigen lassen.
2. **WebDAV-URL notieren**: bei Hetzner Storage Share
   `https://<instanz>.<subdomain>.your-storageshare.de/remote.php/dav`
   (in den Nextcloud-Einstellungen unter *Einstellungen/Verwaltung → Teilen → WebDAV*).
3. **Speichern**: das Tool mit `webdav_url`, `username` und `app_password` aufrufen.
   Das Tool prüft die Zugangsdaten mit einem günstigen WebDAV-Request gegen die
   Instanz, bevor etwas gespeichert wird; ungültige Zugangsdaten werden mit einer
   Fehlermeldung abgelehnt und nicht persistiert.

Die Zugangsdaten werden Fernet-verschlüsselt (derselbe Key wie der OAuth-State,
`MCP_OAUTH_STORAGE_KEY`) in der Firestore-`(default)`-Datenbank gespeichert,
in einer eigenen Collection (`nextcloud-credentials`). Der Speicher-Schlüssel ist
die lowercased E-Mail-Adresse aus dem Google-Token des Aufrufers — kein Tool-Parameter
kann den Schlüssel setzen oder überschreiben, daher erreicht jede Person nur ihr
eigenes Nextcloud-Konto.

### stdio-Fallback: ein Konto per Umgebungsvariablen

Der lokale stdio-Transport läuft ohne OAuth-Identität. Dafür unterstützt das Toolset
eine Einzelkonto-Konfiguration über drei Umgebungsvariablen — alle drei oder keiner:

| Variable | Bedeutung |
|---|---|
| `NEXTCLOUD_WEBDAV_URL` | WebDAV-URL des Nextcloud (Storage Share), endet auf `/remote.php/dav` |
| `NEXTCLOUD_USERNAME` | Nextcloud-Benutzername des Kontos |
| `NEXTCLOUD_APP_PASSWORD` | App-Passwort aus der Nextcloud-Weboberfläche |

Bei Teil-Konfiguration melden die Tools einen klaren Fehler mit den fehlenden
Variablen. Authentifizierte Aufrufer (HTTP-Transport) ignorieren diese Variablen
stets — gespeicherte Zugangsdaten gewinnen.

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

# Runtime-Service-Account (Identität des Cloud-Run-Service; bewusst ohne Rollen)
gcloud iam service-accounts create assistant-mcp-runtime \
  --project=rubenschulze-sandbox --display-name="assistant-mcp Cloud Run runtime"

# Deploy-Service-Account
gcloud iam service-accounts create github-actions-deploy \
  --project=rubenschulze-sandbox --display-name="GitHub Actions deploy"

# Rollen (Bild schreiben, Service deployen, Runtime-SA nutzen dürfen)
gcloud artifacts repositories add-iam-policy-binding assistant-mcp \
  --location=europe-west1 --project=rubenschulze-sandbox \
  --member="serviceAccount:github-actions-deploy@rubenschulze-sandbox.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# run.admin auf Projektebene: der Cloud-Run-Service existiert vor dem ersten
# Deploy noch nicht, ein Binding auf dem Service wäre daher unmöglich
gcloud projects add-iam-policy-binding rubenschulze-sandbox \
  --member="serviceAccount:github-actions-deploy@rubenschulze-sandbox.iam.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud iam service-accounts add-iam-policy-binding \
  assistant-mcp-runtime@rubenschulze-sandbox.iam.gserviceaccount.com \
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
Streamable-HTTP-Transport von FastMCP unter `/mcp` — im stateless-Modus (siehe
„Startup-Probe und stateless HTTP“).
