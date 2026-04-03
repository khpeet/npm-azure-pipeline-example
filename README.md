# New Relic NPM Container Automation

Automated Azure based CI/CD pipeline for managing New Relic Network Performance Monitoring (NPM) containers on Linux hosts. Triggered entirely through **New Relic Workflow Automation** — no manual deployments, no git interactions after initial setup.

## How It Works

```
New Relic Workflow Automation
    │
    │  HTTP POST (Azure DevOps REST API)
    ▼
Azure DevOps Pipeline
    │
    ├── Validate parameters
    ├── Generate SNMP/Docker config from devices JSON
    ├── (Optional) Auto-discover devices for vendor profiles
    └── Deploy via SSH to Linux host running NPM
    │
    ▼
Linux Host
    └── ktranslate Docker container collecting SNMP data → New Relic
```

Each pipeline run manages **one container** identified by a unique `containerID`. Supported actions: `create`, `add-devices`, `update-devices`, `remove-devices`, `start`, `stop`, `remove`.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Setup Guide](#setup-guide)
  - [Step 1: Create Azure DevOps Organization and Project](#step-1-create-azure-devops-organization-and-project)
  - [Step 2: Import Code into Azure Repos](#step-2-import-code-into-azure-repos)
  - [Step 3: Create the Pipeline](#step-3-create-the-pipeline)
  - [Step 4: Get New Relic Credentials](#step-4-get-new-relic-credentials)
  - [Step 5: Create Variable Group (Secrets)](#step-5-create-variable-group-secrets)
  - [Step 6: Generate SSH Key Pair](#step-6-generate-ssh-key-pair)
  - [Step 7: Create SSH Service Connection(s)](#step-7-create-ssh-service-connections)
  - [Step 8: Prepare Linux Hosts](#step-8-prepare-linux-hosts)
  - [Step 9: Register Azure AD Application (Service Principal)](#step-9-register-azure-ad-application-service-principal)
  - [Step 10: Configure New Relic Workflow Automation](#step-10-configure-new-relic-workflow-automation)
- [Usage Examples](#usage-examples)
  - [Create a Container (Manual Device Profiles)](#create-a-container-manual-device-profiles)
  - [Create a Container (Auto-Probe Devices)](#create-a-container-auto-probe-devices)
  - [Add Devices to an Existing Container](#add-devices-to-an-existing-container)
  - [Update Devices in an Existing Container](#update-devices-in-an-existing-container)
  - [Change a Device IP (Supported Path)](#change-a-device-ip-supported-path)
  - [Remove Devices from an Existing Container](#remove-devices-from-an-existing-container)
  - [Stop a Container](#stop-a-container)
  - [Remove a Container](#remove-a-container)
  - [SNMPv3 Device Example](#snmpv3-device-example)
- [Pipeline Actions Reference](#pipeline-actions-reference)
  - [Universal: Validate (all actions)](#universal-validate-all-actions)
  - [`create`](#create)
  - [`add-devices`](#add-devices)
  - [`update-devices`](#update-devices)
  - [`remove-devices`](#remove-devices)
  - [`start`](#start)
  - [`stop`](#stop)
  - [`remove`](#remove)
  - [Shared Step Templates](#shared-step-templates)
  - [Key Safety Invariants](#key-safety-invariants)
- [Pipeline Parameters Reference](#pipeline-parameters-reference)
  - [Device Object Fields](#device-object-fields)
  - [`snmp_v3` object fields](#snmp_v3-object-fields)
  - [`update-devices` payload rules](#update-devices-payload-rules)
- [Troubleshooting](#troubleshooting)
  - [Pipeline fails at Validate stage](#pipeline-fails-at-validate-stage)
  - [SSH connection failures](#ssh-connection-failures)
  - [Container fails health check](#container-fails-health-check)
  - [Probe times out](#probe-times-out)
  - [Pipeline runs but nothing happens in New Relic](#pipeline-runs-but-nothing-happens-in-new-relic)
  - [Pipeline execution logging in New Relic](#pipeline-execution-logging-in-new-relic)
  - [How to view pipeline run logs](#how-to-view-pipeline-run-logs)
- [Architecture](#architecture)
  - [File Structure](#file-structure)
  - [Host File Layout](#host-file-layout)

---

## Prerequisites

Before starting, you need:

| Requirement | Details |
|-------------|---------|
| **Azure account** | Free tier works. Sign up at [azure.microsoft.com](https://azure.microsoft.com/free/) |
| **New Relic account** | With Network Performance Monitoring enabled. Sign up at [newrelic.com](https://newrelic.com/signup) |
| **Linux host(s)** | Ubuntu 20.04+ or similar. Must have Docker/docker-compose installed and SSH access. Can be on-prem, cloud VM, or any Linux server reachable via SSH |
| **Workstation** | With `git` CLI installed (for initial repo setup only) |

---

## Setup Guide

### Step 1: Create Azure DevOps Organization and Project

1. Go to [dev.azure.com](https://dev.azure.com)
2. Sign in with your Azure/Microsoft account
3. If prompted, create a new organization:
   - Click **New organization**
   - Choose a name (e.g., `my-org`)
   - Select your region
4. Create a new project:
   - Click **New Project**
   - Name: `newrelic-npm` (or your choice)
   - Visibility: **Private**
   - Click **Create**

### Step 2: Import Code into Azure Repos

1. In your Azure DevOps project, click **Repos** in the left sidebar
2. Your repo will be empty. Click **Import** to import from a local repository, or push manually:

**Option A — Push from local (recommended):**
```bash
cd /path/to/this/project
git init
git add -A
git commit -m "initial commit: NPM automation pipeline"
git remote add origin https://dev.azure.com/{your-org}/{your-project}/_git/{your-project}
git push -u origin main
```

> Replace `{your-org}` and `{your-project}` with your actual organization and project names. Azure DevOps will typically prompt for credentials — use your Microsoft account or a PAT.

**Option B — Upload via browser:**
- Use the Azure DevOps web UI to upload files directly (less ideal for the full project).

3. Verify all files appear in the repo, especially `pipelines/manage-container.yml`.

### Step 3: Create the Pipeline

1. In your project, click **Pipelines** in the left sidebar
2. Click **Create Pipeline**
3. Select **Azure Repos Git**
4. Select your repository
5. Select **Existing Azure Pipelines YAML file**
6. Branch: `main`, Path: `/pipelines/manage-container.yml`
7. Click **Continue**, then **Save** (do NOT click "Run" yet — we need to set up secrets first)
8. **Note your Pipeline ID** — you'll need this for New Relic. Find it in the URL:
   ```
   https://dev.azure.com/{org}/{project}/_build?definitionId=YOUR_PIPELINE_ID
   ```

### Step 4: Get New Relic Credentials

#### User/Ingest Keys & Account ID
1. Log in to [one.newrelic.com](https://one.newrelic.com)
2. Click your account menu (bottom-left) → **API Keys**
3. Click **Create a key**
   - Key type: **Ingest - License**
   - Name: `ktranslate-ingest-npm` (or your choice)
4. Click **Create a key** again
   - Key type: **User**
   - Name: `ktranslate-user-npm` (or your choice)
5. Copy these keys — the ingest key is your `NR_INGEST_KEY` and the User key will be used in [New Relic Secrets](#store-credentials-as-new-relic-secrets) section
6. Copy the account id for the new row that was created in the table. This is the account your keys were created against and is your `NR_ACCOUNT_ID`


### Step 5: Create Variable Group (Secrets)

1. Go to **Pipelines → Library** in the left sidebar
2. Click **+ Variable group**
3. Name: `newrelic-npm-secrets`
4. Add these variables:

| Name | Value | Click lock icon? |
|------|-------|-----------------|
| `NR_INGEST_KEY` | Your New Relic Ingest License key | Yes (secret) |
| `NR_ACCOUNT_ID` | Your New Relic Account ID | Yes (secret) |

5. Click **Save**
6. Click **Pipeline permissions** → **+** → select your pipeline → Close the window

> **Where to find these values:** See [Step 4: Get New Relic Credentials](#step-4-get-new-relic-credentials).

### Step 6: Generate SSH Key Pair

On your local workstation, generate an SSH key pair that the pipeline will use to connect to your Linux hosts:

```bash
ssh-keygen -t ed25519 -C "azure-pipeline@devops" -f ~/.ssh/azure-pipeline-key -N ""
```

This creates:
- `~/.ssh/azure-pipeline-key` — private key (used by Azure DevOps)
- `~/.ssh/azure-pipeline-key.pub` — public key (installed on each Linux host)

**Keep the private key secure.** You'll paste it into Azure DevOps in the next step.

### Step 7: Create SSH Service Connection(s)

Create one SSH service connection per Linux host:

1. Go to **Project Settings** (gear icon, bottom-left) → **Service connections**
2. Click **Create service connection** → **SSH**
3. Fill in:
   - **Host name**: Your Linux host's IP or FQDN (e.g., `10.0.1.50`)
   - **Port number**: `22`
   - **Username**: The deployment user (e.g., `azpipeline` — see [Step 8](#step-8-prepare-linux-hosts))
   - **Password or private key**: Select **Private Key**, paste or upload contents of `~/.ssh/azure-pipeline-key`
   - **Service connection name**: `ssh-{descriptive-name}` (e.g., `ssh-datacenter-01`)
   - **Description**: Optional (e.g., "Datacenter 01 Linux host")
4. Check **Grant access permission to all pipelines**
5. Click **Save**

> **Naming convention:** The `targetHost` parameter in the pipeline must match the service connection name exactly. Use a consistent naming scheme like `ssh-datacenter-01`, `ssh-office-02`, etc.

Repeat for each Linux host you want to manage containers on.

### Step 8: Prepare Linux Hosts

Run these commands on **each** Linux host that will run NPM containers:

```bash
# Install Docker (if not already installed)
curl -fsSL https://get.docker.com | sh

# Create deployment user
sudo useradd -m -s /bin/bash azpipeline

# Add to docker group (allows running docker without sudo)
sudo usermod -aG docker azpipeline

# Create SSH directory and add public key
sudo mkdir -p /home/azpipeline/.ssh
sudo chmod 700 /home/azpipeline/.ssh

# Paste the contents of your azure-pipeline-key.pub file here:
echo "YOUR_PUBLIC_KEY_HERE" | sudo tee /home/azpipeline/.ssh/authorized_keys
sudo chmod 600 /home/azpipeline/.ssh/authorized_keys
sudo chown -R azpipeline:azpipeline /home/azpipeline/.ssh

# Create ktranslate config directory
sudo mkdir -p /etc/ktranslate
sudo chown azpipeline:azpipeline /etc/ktranslate

# Verify Docker works for the deployment user
sudo -u azpipeline docker run --rm hello-world
```

> Replace `YOUR_PUBLIC_KEY_HERE` with the actual contents of `~/.ssh/azure-pipeline-key.pub` from [Step 5](#step-5-generate-ssh-key-pair).

> **Host prerequisites:** Docker and the `docker-compose` CLI. No Python or additional packages are needed on the host — all scripting logic runs on the Microsoft-hosted pipeline runner.

### Step 9: Register Azure AD Application (Service Principal)

New Relic Workflow Automation authenticates against the Azure DevOps REST API using an Azure AD service principal. This replaces the need for a Personal Access Token.

#### Create the App Registration

1. Go to [portal.azure.com](https://portal.azure.com) and sign in
2. Search for **Microsoft Entra ID** (formerly Azure Active Directory) → click **Add** → **App registration**
3. Configure:
   - **Name**: `newrelic-workflow-automation` (or your choice)
   - **Supported account types**: **Single tenant only - Default directory** (or what your org prefers)
   - Leave Redirect URI blank
4. Click **Register**
5. On the app overview page, copy and save:
   - **Application (client) ID** - this is your `clientId`
   - **Object ID** - this will be within the [Grant Access to Azure Devops](#grant-access-to-azure-devops) steps
   - **Directory (tenant) ID** - this is your `tenantId`

#### Create a Client Secret

1. In your app registration, click **Certificates & secrets** (left sidebar, under Manage)
2. Under **Client secrets**, click **+ New client secret**
3. Set a description (e.g., `newrelic-workflow`) and choose an expiration
4. Click **Add**
5. **Copy the secret Value immediately** — it will not be shown again. This is your `clientSecret`.

> Tip: Set a calendar reminder before the secret expires so you can rotate it before workflows stop working.

#### Grant Access to Azure DevOps

The service principal needs permission to queue builds in your Azure DevOps organization:

1. In **Azure DevOps**, go to **Organization Settings** (bottom-left gear icon) → **Users**
2. Click **Add users**
3. Input the `Object ID` previously copied during the previous steps
4. Set **Access level**: `Basic`
5. Set **Add to projects**: `NR-NPM` (or whatever you called the project)
6. Uncheck `Send email invites`
7. Click **Add**
8. Navigate to your pipeline: **Pipelines → [your pipeline] → ⋯ (ellipses top right) → Manage security**
9. Find your service principal in the list and set **Queue builds** to **Allow**

> NOTE: if you are unable to add the service principal user, validate that your Azure DevOps org is connected to the Azure tenant that the service principal was created in. To validate, navigate to `Organization settings` from your root DevOps org page, click `Microsoft Entra`, and confirm if you see the correct tenant.

> For more information on this process, see [Azure docs](https://learn.microsoft.com/en-us/azure/devops/integrate/get-started/authentication/service-principal-managed-identity?view=azure-devops)

#### Store Credentials as New Relic Secrets

New Relic Workflow Automation uses a [secrets manager to store credentials](https://docs.newrelic.com/docs/workflow-automation/limitations-and-faq/workflow-best-practices/#secure-credentials) referenced in workflow YAML files.

1. Go to New Relic's [GraphQL Explorer](https://api.newrelic.com/graphiql)
2. Input your User API key generated in [Step 4](#step-4-get-new-relic-credentials)
3. Add the following two secrets, submitting a graphql mutation for each secret (**NOTE:** The account id and namespace should be the same for both submissions; the key, description, and value should differ):

| Secret name | Value |
|-------------|-------|
| `azure-client-id` | App Registration `clientId` |
| `azure-client-secret` | App Registration `clientSecret` |

```bash
mutation {
    secretsManagementCreateSecret(
      scope: {type: ACCOUNT id: "NR_ACCOUNT_ID"}
      namespace: "azure"
      key: "azure-client-id"
      description: "Azure Client ID for npm pipeline"
      value: "YOUR_AZURE_ID_OR_SECRET"
    ) {
      key
    }
  }
```


These are referenced in the workflow YAML as `${{ :secrets:azure:azure-client-id }}` and `${{ :secrets:azure:azure-client-secret }}`.

> NOTE: The only way to store credentials today is via API - a UI is coming soon. You can also programmatically create this outside of the graphql explorer via curl, or whatever request means you're comfortable with.

### Step 10: Configure New Relic Workflow Automation

New Relic Workflow Automation triggers the Azure DevOps pipeline with two `http.post` steps and then emits a trigger log to New Relic. A ready-to-use workflow template is included in this repo at [newrelic/newrelic-workflow.yml](newrelic/newrelic-workflow.yml).

#### Customize the Workflow Template

Before importing the workflow, open [newrelic/newrelic-workflow.yml](newrelic/newrelic-workflow.yml) and update the four placeholder defaults to match your environment:

```yaml
workflowInputs:
  azureTenantId:
    defaultValue: "your-tenant-id"   # Replace with your Azure AD tenant ID (GUID)
  azureDevOpsOrg:
    defaultValue: "your-org"         # Replace with your Azure DevOps organization name
  azureDevOpsProject:
    defaultValue: "your-project"     # Replace with your Azure DevOps project name
  pipelineId:
    defaultValue: 0                  # Replace with your pipeline ID (from Step 3)
```

> **Finding your pipeline ID:** In Azure DevOps, open the pipeline and look at the URL: `.../_build?definitionId=YOUR_PIPELINE_ID`

The credential inputs (`azureClientId`, `azureClientSecret`) already default to the secret names you created in [Step 8](#step-8-register-azure-ad-application-service-principal) — no changes needed unless you used different secret names.

#### Create the Workflow in New Relic

1. Log in to [one.newrelic.com](https://one.newrelic.com)
2. Go to **All Capabilities → Workflow Automation**
3. Click **Create your own**
4. In the YAML editor, paste the full contents of `newrelic/newrelic-workflow.yml` (with your customizations from above)
5. Click **Save** to deploy

#### Trigger Options

| Method | How |
|--------|-----|
| **UI** | Deploy [NPM Manager app](https://github.com/khpeet/nr1-npm-manager) |
| **On-demand (manual)** | From the Workflow Automation UI, click the workflow → **Run** → supply `containerID`, `targetHost`, `containerAction`, and other inputs |
| **Scheduled** | Add a cron schedule in the Workflow Automation configuration |

> **References:** [New Relic Workflow Automation](https://docs.newrelic.com/docs/workflow-automation/introduction-to-workflow/) · [http.post action](https://docs.newrelic.com/docs/workflow-automation/setup-and-configure/actions-catalog/http/http-post/)

---

## Usage Examples

The examples below show the `workflowInputs` values to provide when running the `npm-manage-container` workflow from the New Relic Workflow Automation UI (or when triggered from an alert or schedule). All inputs not shown use their defaults from [`newrelic/newrelic-workflow.yml`](newrelic/newrelic-workflow.yml).

### Create a Container (Manual Device Profiles)

```yaml
workflowInputs:
  containerAction: "create"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
  devices: '[{"device_name":"switch-floor-01","device_ip":"10.0.1.1","snmp_comm":"public","mib_profile":"cisco-catalyst.yml","oid":".1.3.6.1.4.1.9.1.1","user_tags":{"site":"dc01","owning_team":"network_ops"}},{"device_name":"router-core","device_ip":"10.0.1.254","snmp_comm":"private","poll_time_sec":120}]'
  snmpCommunity: "public"
  probeDevices: false
```

### Create a Container (Auto-Probe Devices)

Omit `oid` and `mib_profile` from devices and set `probeDevices` to `true`. The pipeline will automatically detect device vendor profiles:

```yaml
workflowInputs:
  containerAction: "create"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
  devices: '[{"device_name":"switch-floor-01","device_ip":"10.0.1.1","snmp_comm":"public"},{"device_name":"router-core","device_ip":"10.0.1.254","snmp_comm":"private"}]'
  snmpCommunity: "public"
  probeDevices: true
```

### Add Devices to an Existing Container

Provide only the **new** devices to add. The pipeline fetches the current `devices.yaml` from the host and merges them in. Duplicate IPs are skipped with a warning.

```yaml
workflowInputs:
  containerAction: "add-devices"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
  devices: '[{"device_name":"ap-lobby","device_ip":"10.0.1.50","snmp_comm":"public","user_tags":{"site":"hq","role":"wireless"}},{"device_name":"vip-lb-01","device_ip":"10.0.1.60","provider":"kentik_ping","ping_only":true,"ping_interval_sec":5,"user_tags":{"owning_team":"team-x"}}]'
  snmpCommunity: "public"
  probeDevices: false
```

### Update Devices in an Existing Container

Provide patch objects in the same `devices` array. Each item is matched by immutable `device_ip`; omitted fields are preserved; supplied fields overwrite existing values; and `device_name` may be changed to rename the YAML map key.

```yaml
workflowInputs:
  containerAction: "update-devices"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
  devices: '[{"device_ip":"10.0.1.50","device_name":"ap-lobby-renamed","description":"Lobby AP refreshed","user_tags":{"site":"hq","role":"wireless"}},{"device_ip":"10.0.1.60","poll_time_sec":60,"provider":"kentik_ping","ping_only":true,"ping_interval_sec":10}]'
```

If you include `snmp_v3` in an update, provide the full nested object. Partial `snmp_v3` patches are rejected to avoid silently resetting omitted credentials.

### Change a Device IP (Supported Path)

`update-devices` does **not** support changing `device_ip`. To move a device to a new IP, add the replacement device and remove the old one in separate runs:

```yaml
# Run 1
workflowInputs:
  containerAction: "add-devices"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
  devices: '[{"device_name":"ap-lobby","device_ip":"10.0.2.50","snmp_comm":"public"}]'

# Run 2
workflowInputs:
  containerAction: "remove-devices"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
  removeDevices: '[{"device_ip":"10.0.1.50"}]'
```

### Remove Devices from an Existing Container

Only `device_ip` is required in the `removeDevices` array:

```yaml
workflowInputs:
  containerAction: "remove-devices"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
  removeDevices: '[{"device_ip":"10.0.1.1"},{"device_ip":"10.0.1.254"}]'
```

### Stop a Container

```yaml
workflowInputs:
  containerAction: "stop"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
```

### Remove a Container

```yaml
workflowInputs:
  containerAction: "remove"
  containerID: "npm-dc01-01"
  targetHost: "ssh-datacenter-01"
```

### SNMPv3 Device Example

Include SNMPv3 credentials in the `devices` JSON:

```yaml
workflowInputs:
  containerAction: "create"
  containerID: "npm-dc01-02"
  targetHost: "ssh-datacenter-01"
  devices: '[{"device_name":"firewall-01","device_ip":"10.0.1.10","snmp_v3":{"user_name":"snmpuser","authentication_protocol":"SHA","authentication_passphrase":"authpass123","privacy_protocol":"AES","privacy_passphrase":"privpass123","context_engine_id":"80:00:01:01:0a:14:1e:28","context_name":"core-routing"}}]'
```

---

## Pipeline Actions Reference

Every pipeline run is routed by the `containerAction` parameter. This section documents what each action does internally — the stages it runs, the steps those stages trigger, and the end result on the target host.

### Universal: Validate (all actions)

**File:** [pipelines/manage-container.yml](pipelines/manage-container.yml) — `ValidateParams` job

Before any action template is entered, the pipeline runs a validation job that checks all supplied parameters. If any check fails, the pipeline exits immediately and no host is ever contacted.

| Check | Rule |
|-------|------|
| `containerID` | Non-empty, lowercase alphanumeric + hyphens, ≤ 63 characters |
| `targetHost` | Non-empty, alphanumeric + hyphens/underscores |
| `devices` JSON | Required for `create`/`add-devices`: valid JSON array, ≥ 1 item, each with a valid IPv4 `device_ip` and a `device_name` |
| `devices` JSON (update) | Required for `update-devices`: valid JSON array, ≥ 1 item, each with a valid IPv4 `device_ip`; partial fields are allowed, duplicate target IPs are rejected, and `probeDevices=true` is not supported |
| `removeDevices` JSON | Required for `remove-devices`: valid JSON array, ≥ 1 item, each with `device_ip` |

SNMP community strings are redacted from all log output.

---

### `create`

**File:** [pipelines/actions/create.yml](pipelines/actions/create.yml)  
**Purpose:** Full lifecycle boot of a new `ktranslate-{containerID}` Docker container on the target host.  
**Required parameters:** `containerID`, `targetHost`, `devices`  
**Optional parameters:** `snmpCommunity`, `probeDevices`, `force`

#### Stage 1 — `GenerateConfig`

Runs on the Azure DevOps pipeline runner.

| Step | What it does |
|------|--------------|
| Checkout repo | Makes scripts and templates available on the runner |
| Run [scripts/generate_config.py](scripts/generate_config.py) | Generates `snmp-base.yaml` (with `@devices.yaml` include and a union of all `discovered_mibs` as `mibs_enabled`) and `devices.yaml` (flat device map) into the artifact staging directory |
| Render docker-compose template | Substitutes `{{CONTAINER_ID}}` in [templates/docker-compose.template.yml](templates/docker-compose.template.yml) → `docker-compose.yml` |
| Validate config | Runs Python YAML structural validation against all generated files; halts pipeline on any error |
| Publish artifact `container-config` | Makes `snmp-base.yaml`, `devices.yaml`, and `docker-compose.yml` available to downstream stages |

#### Stage 2 — `ProbeDevices` *(opt-in — skipped when `probeDevices=false`)*

Condition: `GenerateConfig` succeeded **and** `probeDevices == true`

Runs a temporary discovery container on the host to fingerprint each device and enrich the config with vendor profiles.

| Step | What it does |
|------|--------------|
| Run [scripts/generate_probe_config.py](scripts/generate_probe_config.py) | Creates `snmp-probe.yaml` — a ktranslate discovery config scoped to only the supplied devices |
| Copy probe YAML to host | Uploads `snmp-probe.yaml` → `/etc/ktranslate/probe-{containerID}/` on the host |
| Copy [scripts/run-probe.sh](scripts/run-probe.sh) to host | Uploads the probe runner script → `/etc/ktranslate/scripts/` |
| SSH — run probe | Executes `run-probe.sh --container-id {containerID}` on the host; launches a **temporary** `docker run --rm kentik/ktranslate:v2` container that writes `discovered-snmp.yaml` with each device's `oid`, `mib_profile`, `provider`, and `discovered_mibs` |
| SSH — retrieve output | `base64`-encodes `discovered-snmp.yaml` and captures it as a pipeline output variable; the temporary probe directory is deleted from the host |
| Merge probe results | Runner Python script decodes and merges `oid`, `mib_profile`, `provider`, `description`, and `discovered_mibs` from probe output into the original devices JSON (caller-supplied values always win); regenerates `snmp-base.yaml` and `devices.yaml` via [scripts/lib/device_utils.py](scripts/lib/device_utils.py) |
| Re-validate config | Same YAML structural validation as Stage 1 |
| Publish artifact `container-config-enriched` | Publishes the probe-enriched config as a separate artifact for the deploy stage |

#### Stage 3 — `Deploy`

Condition: `GenerateConfig` succeeded + `ProbeDevices` succeeded **or skipped**

| Step | What it does |
|------|--------------|
| Download config artifact | Pulls `container-config` when probing is skipped, or `container-config-enriched` when probing ran successfully |
| Final validate config | Belt-and-suspenders YAML validation before anything touches the host |
| SSH — pre-flight check | Checks if `/etc/ktranslate/{containerID}` already exists on the host. If yes + `force=false` → **pipeline halts with an error**. If yes + `force=true` → timestamps and backs up all three config files (`.bak.{timestamp}`) then continues. If no → proceeds normally |
| Copy config to host | Uploads `snmp-base.yaml`, `devices.yaml`, `docker-compose.yml` → `/etc/ktranslate/{containerID}/` |
| Copy scripts to host | Uploads [scripts/manage-container.sh](scripts/manage-container.sh) and [scripts/healthcheck.sh](scripts/healthcheck.sh) → `/etc/ktranslate/scripts/` |
| SSH — create container | Injects `NR_INGEST_KEY` and `NR_ACCOUNT_ID` as env vars; runs `manage-container.sh --action create --container-id {containerID}` which writes `/etc/ktranslate/{containerID}/.env` (chmod 600), runs `docker pull kentik/ktranslate:v2`, and runs `docker-compose up -d` |
| SSH — health check | Runs `healthcheck.sh ktranslate-{containerID}` — polls `docker inspect` for up to 30 seconds for `running` state, then scans container logs for `fatal`/`panic` |
| Publish result to New Relic | HTTP POST to New Relic Logs API with action, result, containerID, and pipeline run URL (runs `always()` — fires even on failure) |

---

### `add-devices`

**File:** [pipelines/actions/add-devices.yml](pipelines/actions/add-devices.yml)  
**Purpose:** Append new SNMP devices to an already-running container and restart it to pick up the changes.  
**Required parameters:** `containerID`, `targetHost`, `devices`  
**Optional parameters:** `snmpCommunity`, `probeDevices`

#### Stage 1 — `ProbeDevices` *(opt-in — skipped when `probeDevices=false`)*

Identical fingerprinting flow to `create`'s `ProbeDevices` stage, but instead of regenerating the full `container-config` artifact it emits a slimmer artifact containing only `enriched-devices.json` — the caller-supplied devices JSON enriched with discovered fields.

#### Stage 2 — `AddDevices`

| Step | What it does |
|------|--------------|
| Fetch current devices from host | SSH to host: `base64`-encodes `/etc/ktranslate/{containerID}/devices.yaml` → captured as pipeline variable `currentDevicesB64`. Fails immediately if the file does not exist (i.e., the container was never created). |
| Validate fetched devices | Decodes and runs `validate_devices_yaml()` from [scripts/lib/validate_yaml.py](scripts/lib/validate_yaml.py) against the host-side file; aborts if the host config is corrupted before any merge is attempted |
| Merge new devices | Runner Python calls [scripts/manage_devices.py](scripts/manage_devices.py) `--action add`: decodes the fetched `devices.yaml`, loads probe-enriched devices if available (otherwise raw `devices` param), deduplicates by `device_ip` (skips with a warning if an IP already exists), appends new entries, and recomputes `mibs_enabled` as a union of all `discovered_mibs` across all devices |
| Validate merged config | YAML structural validation of the merged output before the host is touched |
| Backup existing config | SSH: timestamps and copies `devices.yaml` + `snmp-base.yaml` to `.bak.{timestamp}`; retains only the 5 most recent backups |
| Upload updated config | SCP: uploads merged `devices.yaml` + `snmp-base.yaml` → `/etc/ktranslate/{containerID}/`; then SSH `chmod 644` both files so the container user can read them through the existing `:ro` bind mounts |
| Copy scripts to host | Uploads `manage-container.sh` + `healthcheck.sh` |
| Restart and health check | SSH: `manage-container.sh --action restart` (`docker-compose down && up -d`); then `healthcheck.sh ktranslate-{containerID}` |
| Publish result to New Relic | HTTP POST to New Relic Logs API (runs `always()`) |

---

### `update-devices`

**File:** [pipelines/actions/update-devices.yml](pipelines/actions/update-devices.yml)  
**Purpose:** Patch existing devices in a running container by immutable `device_ip`, optionally renaming `device_name`, then restart the container.  
**Required parameters:** `containerID`, `targetHost`, `devices`

#### Stage — `UpdateDevices`

| Step | What it does |
|------|--------------|
| Fetch current devices from host | Same SSH base64-fetch as `add-devices` |
| Validate fetched devices | Same host-side corruption check as `add-devices` |
| Apply device patches | Runner Python calls [scripts/manage_devices.py](scripts/manage_devices.py) `--action update`: decodes `devices.yaml`, matches each patch by `device_ip`, preserves omitted fields, overwrites only the supplied fields, renames the YAML map key when `device_name` changes, rejects unknown `device_ip` targets, and fails before write-time if a rename would collide with another key |
| Validate updated config | YAML structural validation before touching the host |
| Backup existing config | SSH: timestamp backup with max 5 retained |
| Upload updated config | SCP: updated `devices.yaml` + `snmp-base.yaml` → host with `chmod 644` |
| Copy scripts to host | Uploads `manage-container.sh` + `healthcheck.sh` |
| Restart and health check | `docker-compose down && up -d` + `healthcheck.sh` |
| Publish result to New Relic | HTTP POST to New Relic Logs API (runs `always()`) |

**Update contract:**
- `device_ip` is the immutable match key.
- Omitted fields are preserved.
- Supplied fields overwrite the existing value.
- `device_name` may change, which renames the top-level YAML key.
- If `snmp_v3` is supplied, it must be a full replacement object.
- `device_ip` changes must be handled with `add-devices` + `remove-devices`.

Common update failures are: unknown `device_ip`, duplicate `device_ip` targets in the request, `device_name` collisions, invalid field types/values, and partial `snmp_v3` payloads.

---

### `remove-devices`

**File:** [pipelines/actions/remove-devices.yml](pipelines/actions/remove-devices.yml)  
**Purpose:** Remove specific devices from a running container's inventory by `device_ip`, then restart the container.  
**Required parameters:** `containerID`, `targetHost`, `removeDevices`

#### Stage — `RemoveDevices`

| Step | What it does |
|------|--------------|
| Fetch current devices from host | Same SSH base64-fetch as `add-devices` |
| Validate fetched devices | Same host-side corruption check as `add-devices` |
| Remove matched devices | Runner Python calls [scripts/manage_devices.py](scripts/manage_devices.py) `--action remove`: decodes `devices.yaml`, removes each entry whose `device_ip` matches an entry in `removeDevices` (warns but continues if an IP is not found), recomputes `mibs_enabled` from remaining devices, and writes updated `devices.yaml` + `snmp-base.yaml` |
| Validate updated config | YAML structural validation before touching the host |
| Backup existing config | SSH: timestamp backup with max 5 retained |
| Upload updated config | SCP: updated `devices.yaml` + `snmp-base.yaml` → host with `chmod 644` |
| Copy scripts to host | Uploads `manage-container.sh` + `healthcheck.sh` |
| Restart and health check | `docker-compose down && up -d` + `healthcheck.sh` |
| Publish result to New Relic | HTTP POST to New Relic Logs API (runs `always()`) |

---

### `start`

**File:** [pipelines/actions/start.yml](pipelines/actions/start.yml)  
**Purpose:** Start a previously stopped container by resuming the preserved Docker container using the configuration files already on disk. No config regeneration, image pull, or container recreation is performed.  
**Required parameters:** `containerID`, `targetHost`

#### Stage — `Deploy`

| Step | What it does |
|------|--------------|
| Copy scripts to host | Uploads `manage-container.sh` + `healthcheck.sh` → `/etc/ktranslate/scripts/` |
| SSH — start container | Runs `manage-container.sh --action start --container-id {containerID}`: validates that all four config files are present on disk (`snmp-base.yaml`, `devices.yaml`, `docker-compose.yml`, `.env`) and confirms the stopped container still exists. If the container is already running, exits cleanly. Otherwise runs `docker start` on the preserved container, resuming the same container instance that was previously stopped. |
| SSH — health check | Runs `healthcheck.sh ktranslate-{containerID}` — same post-deploy health verification as `create` |
| Publish result to New Relic | HTTP POST to New Relic Logs API (runs `always()`) |

> `start` is the complement to `stop`. It requires the container itself and its config directory to still be present on disk; if the container was fully removed with `remove`, a new `create` is needed instead.

---

### `stop`

**File:** [pipelines/actions/stop-remove.yml](pipelines/actions/stop-remove.yml)  
**Purpose:** Stop a running container while preserving all configuration files on the host.  
**Required parameters:** `containerID`, `targetHost`

#### Stage — `Deploy`

| Step | What it does |
|------|--------------|
| Copy scripts to host | Uploads `manage-container.sh` + `healthcheck.sh` → `/etc/ktranslate/scripts/` |
| SSH — stop container | Runs `manage-container.sh --action stop --container-id {containerID}`: executes `docker stop` against the running container. The container is left in Docker in a stopped state, and all files in `/etc/ktranslate/{containerID}/` are **preserved** on disk. |
| Publish result to New Relic | HTTP POST to New Relic Logs API (runs `always()`) |

> The preserved container and config mean a subsequent `start` can bring the same container back online without re-supplying any parameters or device data.

---

### `remove`

**File:** [pipelines/actions/stop-remove.yml](pipelines/actions/stop-remove.yml)  
**Purpose:** Stop and fully tear down a container, deleting all configuration from the host.  
**Required parameters:** `containerID`, `targetHost`

#### Stage — `Deploy`

| Step | What it does |
|------|--------------|
| Copy scripts to host | Uploads `manage-container.sh` + `healthcheck.sh` → `/etc/ktranslate/scripts/` |
| SSH — remove container | Runs `manage-container.sh --action remove --container-id {containerID}`: stops the container if it is running, removes the stopped container from Docker, then executes `rm -rf /etc/ktranslate/{containerID}`. The container is removed from Docker **and** the entire config directory is permanently deleted from the host. |
| Publish result to New Relic | HTTP POST to New Relic Logs API (runs `always()`) |

> This action is irreversible. All config files, backups, and the `.env` file are deleted. A new `create` would be needed to restore the container.

---

### Shared Step Templates

All reusable step templates live in [pipelines/templates/steps/](pipelines/templates/steps/). They are included by the action files rather than duplicated.

| Template | What it does | Used by |
|----------|--------------|---------|
| [install-python-deps.yml](pipelines/templates/steps/install-python-deps.yml) | Installs Python dependencies (`pyyaml`) on the runner before any `PythonScript@0` tasks | `create`, `add-devices`, `update-devices`, `remove-devices` |
| [copy-scripts-to-host.yml](pipelines/templates/steps/copy-scripts-to-host.yml) | SCP `manage-container.sh` + `healthcheck.sh` → `/etc/ktranslate/scripts/` on host | All actions |
| [publish-result-to-nr.yml](pipelines/templates/steps/publish-result-to-nr.yml) | HTTP POST to New Relic Logs API with `action`, `containerID`, `targetHost`, `result`, `details`, `requestedBy`, `pipelineRunId`, `pipelineRunUrl`, `source`, and `service`; SNMP secrets redacted; runs `always()` within each action job | All actions |
| [validate-config.yml](pipelines/templates/steps/validate-config.yml) | Runs [scripts/validate_config.py](scripts/validate_config.py) against the config staging directory on the runner; halts pipeline if any file has structural YAML errors | `create`, `add-devices`, `update-devices`, `remove-devices` |
| [fetch-devices-b64.yml](pipelines/templates/steps/fetch-devices-b64.yml) | SSH to host: `base64`-encodes `/etc/ktranslate/{containerID}/devices.yaml` and captures it as pipeline output variable `currentDevicesB64`; fails if the file is missing | `add-devices`, `update-devices`, `remove-devices` |
| [validate-fetched-devices.yml](pipelines/templates/steps/validate-fetched-devices.yml) | Decodes `currentDevicesB64` and runs schema validation on the host-side `devices.yaml`; aborts if the host config is corrupted before any merge begins | `add-devices`, `update-devices`, `remove-devices` |
| [backup-config.yml](pipelines/templates/steps/backup-config.yml) | SSH: copies `devices.yaml` + `snmp-base.yaml` to `.bak.{UTC-timestamp}`; prunes to keep only the 5 most recent backups per container | `add-devices`, `update-devices`, `remove-devices` |
| [upload-config.yml](pipelines/templates/steps/upload-config.yml) | SCP: uploads updated `devices.yaml` + `snmp-base.yaml` → `/etc/ktranslate/{containerID}/`; then SSH `chmod 644` both files | `add-devices`, `update-devices`, `remove-devices` |
| [restart-and-healthcheck.yml](pipelines/templates/steps/restart-and-healthcheck.yml) | SSH: `manage-container.sh --action restart` (`docker-compose down && up -d`); then `healthcheck.sh ktranslate-{containerID}` (polls up to 30 s, scans logs for fatal errors) | `add-devices`, `update-devices`, `remove-devices` |

---

### Key Safety Invariants

> **Validation gates every config write.** `validate-config` always runs before `backup-config`, `upload-config`, or `restart`. If the generated YAML is invalid for any reason, the host is never contacted and the running container keeps its current config.

> **Host-side corruption is caught before merges.** `validate-fetched-devices` checks the host's existing `devices.yaml` before `add-devices`, `update-devices`, or `remove-devices` attempts any merge — preventing a corrupted inventory from silently propagating.

> **`probeDevices` is strictly opt-in.** No autodiscovery runs unless the caller explicitly passes `probeDevices=true`, and `update-devices` rejects probe enrichment entirely in the initial release. The production container never receives a `discovery:` config section.

> **`force=true` on `create` backs up, not overwrites.** When an existing container config is found and `force=true`, all current config files are timestamped and backed up before any new files are written.

> **Action-stage audit trail is unconditional.** The `publish-result-to-nr` step runs with `always()` inside each action job, so once an action template starts it posts success or failure to New Relic Logs even if an earlier step in that job fails. Failures in the top-level `Validate` stage happen before any action job starts, so they do not emit the `source = 'azure-devops-pipeline'` result log.

---

## Pipeline Parameters Reference

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `containerAction` | Yes | — | `create`, `add-devices`, `update-devices`, `remove-devices`, `start`, `stop`, or `remove` |
| `containerID` | Yes | — | Unique container identifier (e.g., `npm-datacenter-01`) |
| `targetHost` | Yes | — | Azure DevOps SSH service connection name (e.g., `ssh-datacenter-01`) |
| `devices` | create, add-devices, update-devices | `[]` | JSON array of device objects to add or patch |
| `removeDevices` | remove-devices | `[]` | JSON array of objects to remove — only `device_ip` is required |
| `snmpCommunity` | No | `public` | Default fallback SNMP community string (for any devices that do not have a string specified) |
| `probeDevices` | No | `false` | Auto-probe devices for sysOID/vendor profile (`create` and `add-devices` only; rejected for `update-devices`) |
| `force` | No | `false` | Allow `create` to overwrite an existing container (backs up existing config first) |

### Device Object Fields

| Field | Required | Description |
|-------|----------|-------------|
| `device_name` | Yes | Human-readable device name |
| `device_ip` | Yes | Device IP address |
| `snmp_comm` | * | SNMPv2c community string |
| `snmp_v3` | * | SNMPv3 credentials object (see example above) |
| `mib_profile` | No | Kentik vendor profile (e.g., `cisco-catalyst.yml`). Auto-detected if `probeDevices=true` |
| `oid` | No | sysObjectID. Auto-detected if `probeDevices=true` |
| `provider` | No | Device type (e.g., `kentik-switch`). Auto-detected if `probeDevices=true` |
| `user_tags` | No | Object of custom key/value attributes appended to any global tags |
| `ping_only` | No | Boolean. Disables SNMP polling and enables RTT polling for that device; supply `provider: kentik_ping` for ping-only devices |
| `ping_interval_sec` | No | Positive integer device override for RTT probe frequency when using `ping_only` |
| `poll_time_sec` | No | Positive integer device override for SNMP poll frequency; overrides the container-level `global.poll_time_sec` default |

> *Note: Either `snmp_comm` or `snmp_v3` is required (not both).

### `snmp_v3` object fields

The `snmp_v3` object follows New Relic's documented schema.

| Field | Required | Description |
|-------|----------|-------------|
| `user_name` | Yes | SNMPv3 user name |
| `authentication_protocol` | Yes | One of `NoAuth`, `MD5`, or `SHA` |
| `authentication_passphrase` | No* | Authentication passphrase |
| `privacy_protocol` | Yes | One of `NoPriv`, `DES`, `AES`, `AES192`, `AES256`, `AES192C`, or `AES256C` |
| `privacy_passphrase` | No* | Privacy passphrase |
| `context_engine_id` | No | SNMPv3 context engine ID |
| `context_name` | No | SNMPv3 context name |

\* `authentication_passphrase` is required when `authentication_protocol` is not `NoAuth`. `privacy_passphrase` is required when `privacy_protocol` is not `NoPriv`.

### `update-devices` payload rules

- Each object must include `device_ip`; it is used only to match an existing device.
- Any omitted field is preserved from the fetched `devices.yaml` entry.
- Any supplied field overwrites the current value.
- `device_name` may be supplied to rename both the stored `device_name` field and the top-level YAML key.
- If `snmp_v3` is supplied, it must contain the full final desired SNMPv3 object for that device. Nested SNMPv3 fields are replaced, not merged, so any optional fields you want to keep must be included again. The object must still include the required SNMPv3 fields listed above.
- To change `device_ip`, add the new device and remove the old one.

---

## Troubleshooting

### Pipeline fails at Validate stage
- **containerID is required** — Ensure `containerID` is provided in `templateParameters`
- **targetHost is required** — Ensure `targetHost` is provided. It must match an SSH service connection name exactly
- **devices is not valid JSON** — Check JSON syntax in the `devices` parameter. Backslash-escape all quotes within the string

### SSH connection failures
- Verify the SSH service connection name in Azure DevOps matches `targetHost` exactly
- Test SSH connectivity: `ssh -i ~/.ssh/azure-pipeline-key azpipeline@HOST_IP`
- Check the host's firewall allows SSH (port 22) from Azure DevOps IP ranges
- Verify the `azpipeline` user exists and has the correct SSH public key

### Container fails health check
- SSH into the host and check logs: `docker logs ktranslate-{containerID}`
- Verify `NR_INGEST_KEY` and `NR_ACCOUNT_ID` are correct in the variable group
- Check that the SNMP devices are reachable from the host: `ping DEVICE_IP`
- Check the generated config: `cat /etc/ktranslate/{containerID}/snmp-base.yaml`

### Probe times out
- The probe has a 120-second timeout. If devices are unreachable, they keep their original values
- Verify SNMP is enabled on the target devices
- Verify the correct community string or SNMPv3 credentials
- Test SNMP from the host: `snmpwalk -v2c -c COMMUNITY DEVICE_IP`

### Pipeline runs but nothing happens in New Relic
- Check container is running: `docker ps | grep ktranslate`
- Check container logs for errors: `docker logs ktranslate-{containerID} --tail 50`
- Verify the New Relic Ingest key is valid and not expired
- Data may take 2-3 minutes to appear in New Relic after container starts

### Pipeline execution logging in New Relic

This automation emits two useful log streams into New Relic:

1. **Workflow trigger logs** from [newrelic/newrelic-workflow.yml](newrelic/newrelic-workflow.yml), written immediately after the workflow requests an Azure AD token and queues the Azure DevOps pipeline. These logs include `containerAction`, `containerID`, `targetHost`, `tokenStatusCode`, `pipelineStatusCode`, `pipelineRunId`, and `pipelineRunUrl`.
2. **Pipeline result logs** from [scripts/publish_result_to_nr.py](scripts/publish_result_to_nr.py), written by [pipelines/templates/steps/publish-result-to-nr.yml](pipelines/templates/steps/publish-result-to-nr.yml) at the end of each action job. These logs include `action`, `containerID`, `targetHost`, `result`, `details`, `pipelineRunId`, `pipelineRunUrl`, `requestedBy`, `source = 'azure-devops-pipeline'`, and `service = 'npm-container-management'`.

Use the pipeline result logs for day-to-day troubleshooting because they carry the final job result and a direct Azure DevOps run URL.

> **Important:** If a run fails in the top-level `Validate` stage, the action job never starts, so no `source = 'azure-devops-pipeline'` result log is emitted. In that case, use the Azure DevOps run log directly and, if needed, look for the workflow trigger log to confirm the run was queued.

#### Example NRQL queries

Inspect all recent pipeline result logs:

```sql
FROM Log
SELECT *
WHERE source = 'azure-devops-pipeline'
SINCE 24 hours ago
```

Show the key result fields for recent runs:

```sql
FROM Log
SELECT timestamp, message, action, containerID, targetHost, result, details, pipelineRunId, pipelineRunUrl, requestedBy
WHERE source = 'azure-devops-pipeline'
SINCE 24 hours ago
```

Find only failed pipeline action runs:

```sql
FROM Log
SELECT *
WHERE source = 'azure-devops-pipeline'
  AND result = 'failure'
SINCE 7 days ago
```

Filter by container:

```sql
FROM Log
SELECT *
WHERE source = 'azure-devops-pipeline'
  AND containerID = 'npm-dc01-01'
SINCE 7 days ago
```

Filter by target host:

```sql
FROM Log
SELECT *
WHERE source = 'azure-devops-pipeline'
  AND targetHost = 'ssh-datacenter-01'
SINCE 7 days ago
```

Graph run outcomes over time:

```sql
FROM Log
SELECT count(*)
WHERE source = 'azure-devops-pipeline'
FACET result
TIMESERIES AUTO
SINCE 7 days ago
```

Inspect workflow trigger events that queued Azure DevOps runs:

```sql
FROM Log
SELECT timestamp, containerAction, containerID, targetHost, tokenStatusCode, pipelineStatusCode, pipelineRunId, pipelineRunUrl
WHERE message = 'NPM Container Pipeline Triggered'
SINCE 24 hours ago
```

### How to view pipeline run logs
1. In Azure DevOps, go to **Pipelines → Runs**
2. Click on the specific run
3. Click on any stage/job to see detailed logs for each step

---

## Architecture

For detailed architecture documentation, see [`docs/architecture.md`](docs/architecture.md).

### File Structure

```
├── newrelic/
│   └── newrelic-workflow.yml          # New Relic Workflow Automation trigger template
├── pipelines/
│   ├── manage-container.yml           # Master router — parameters, Validate, action routing
│   ├── actions/
│   │   ├── create.yml                 # Stages: GenerateConfig → ProbeDevices → Deploy
│   │   ├── add-devices.yml            # Stages: ProbeDevices → AddDevices
│   │   ├── update-devices.yml         # Stage:  UpdateDevices
│   │   ├── remove-devices.yml         # Stage:  RemoveDevices
│   │   └── stop-remove.yml            # Stage:  Deploy (stop or remove)
│   └── templates/steps/               # Reusable step templates
│       ├── install-python-deps.yml    # pip install pyyaml for PythonScript@0 tasks
│       ├── copy-scripts-to-host.yml   # SCP manage-container.sh + healthcheck.sh
│       ├── backup-config.yml          # SSH backup devices.yaml + snmp-base.yaml
│       ├── upload-config.yml          # SCP updated config files to host
│       ├── restart-and-healthcheck.yml # SSH restart container + health check
│       ├── fetch-devices-b64.yml      # SSH fetch devices.yaml as base64 output var
│       ├── validate-config.yml        # YAML structural validation on runner
│       ├── validate-fetched-devices.yml # Validate host-fetched devices.yaml
│       └── publish-result-to-nr.yml   # POST pipeline result to New Relic Logs API
├── scripts/
│   ├── lib/
│   │   └── device_utils.py            # Shared Python: build_device_entry, write YAML helpers
│   ├── generate_config.py              # Generates snmp-base.yaml + devices.yaml (runner)
│   ├── generate_probe_config.py       # Generates ktranslate discovery YAML (runner)
│   ├── manage_devices.py              # Add/update/remove devices with IP-based merge rules (runner)
│   ├── merge_probe_results.py         # Merges probe discovery output into device configs (runner)
│   ├── validate_inputs.py             # Validates pipeline input parameters (runner)
│   ├── validate_config.py             # YAML structural validation wrapper (runner)
│   ├── validate_fetched_devices.py    # Validates host-fetched devices.yaml (runner)
│   ├── publish_result_to_nr.py        # Posts pipeline result to New Relic Logs API (runner)
│   ├── render_template.py             # Template rendering for docker-compose (runner)
│   ├── run-probe.sh                   # Runs temp discovery container (host, pure bash)
│   ├── manage-container.sh            # Container lifecycle on host
│   └── healthcheck.sh                 # Post-deploy health check
├── templates/
│   ├── docker-compose.template.yml    # Docker Compose template
│   ├── snmp-base.template.yaml        # SNMP global config template
│   └── devices.template.yaml          # Empty device inventory template
└── docs/
    └── architecture.md                # Detailed architecture docs
```

### Host File Layout

```
/etc/ktranslate/
├── {containerID}/
│   ├── snmp-base.yaml            # Stable global SNMP config (references devices.yaml via @-include)
│   ├── devices.yaml              # Mutable device inventory (updated by add/update/remove-devices)
│   └── docker-compose.yml        # Container definition
└── scripts/
    └── *.sh                      # Management scripts (copied by pipeline)
```
