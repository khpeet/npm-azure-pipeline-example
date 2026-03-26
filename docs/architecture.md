# Architecture — New Relic NPM CI/CD Pipeline

**Last updated:** 2026-03-26

---

## Overview

This CI/CD pipeline automates the lifecycle management of New Relic NPM (Network Performance Monitoring) containers running on physical Linux hosts in datacenters. Each container runs the **ktranslate** agent (`kentik/ktranslate:v2`) which collects SNMP data from network devices and forwards it to New Relic.

The pipeline is triggered via **New Relic Workflow Automation**, which first obtains an **OAuth2 bearer token from Azure AD** and then calls the **Azure DevOps REST API** to execute a pipeline run. No manual git commits are required to trigger a deployment.

**This pipeline is stateless** — it does not persist container state between runs. All required information (target host, action, etc.) must be provided with each API call. Device inventory state **is** maintained on the host filesystem in `devices.yaml` (see [Split Config Model](#split-config-model)).

---

## Trigger Flow

```
New Relic Workflow Automation
    │  (newrelic/newrelic-workflow.yml)
    │
    ├── Step 1: getAzureToken (http.post)
    │       POST https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token
    │       Body: client_credentials grant, scope=499b84ac.../.default (Azure DevOps resource)
    │       Output: accessToken (bearer token)
    │
      └── Step 2: triggerPipeline (http.post)
            POST https://dev.azure.com/{org}/{project}/_apis/pipelines/{pipelineId}/runs?api-version=7.1
            Header: Authorization: Bearer {accessToken}
          Body: templateParameters (containerAction, containerID, targetHost, devices, ...)
    │
    ▼
Azure Pipeline: pipelines/manage-container.yml  (master router)
    │
    ├── Stage: Validate            → Check all required parameters (all actions)
    │
    ├── [containerAction=create]   → actions/create.yml
    │       ├── Stage: GenerateConfig   → Build snmp-base.yaml + devices.yaml + docker-compose.yml
    │       ├── Stage: ProbeDevices     → (opt-in) Discover devices via temp ktranslate container (auto-discovery)
    │       └── Stage: Deploy          → Copy config to host, run manage-container.sh create, health check scripts
    │
    ├── [containerAction=add-devices] → actions/add-devices.yml
    │       ├── Stage: ProbeDevices     → (opt-in) Discover new devices
    │       └── Stage: AddDevices       → Fetch devices.yaml, dedup by IP, merge, upload, restart
    │
    ├── [containerAction=update-devices] → actions/update-devices.yml
    │       └── Stage: UpdateDevices    → Fetch devices.yaml, patch by IP, upload, restart
    │
    ├── [containerAction=remove-devices] → actions/remove-devices.yml
    │       └── Stage: RemoveDevices    → Fetch devices.yaml, remove by IP, upload, restart
    │
    ├── [containerAction=start]    → actions/start.yml
    │       └── Stage: Deploy          → Copy scripts to host, run manage-container.sh start, health check
    │
    └── [containerAction=stop|remove] → actions/stop-remove.yml
            └── Stage: Deploy          → Copy scripts to host, run manage-container.sh stop|remove
```

---

## Key Concepts

### Container Identity — containerID
Every container has a **unique identifier** (e.g., `npm-datacenter-01`) provided when the container is created. This ID is used to:
- Name the Docker container: `ktranslate-{containerID}`
- Store config on the host: `/etc/ktranslate/{containerID}/`
- Reference the container in all future operations

### Stateless Design
This pipeline does not store or track container state in a database. The caller must provide `containerID` and `targetHost` for every pipeline run. Device inventory state is maintained on the host filesystem in `devices.yaml`.

### Split Config Model
Config is split into two files on the host to allow incremental device management:

| File | Role | Changes When |
|------|------|--------------|
| `snmp-base.yaml` | Stable global config; uses ktranslate `@`-include to load `devices.yaml` | `global:` settings change, or `mibs_enabled` is updated after add/update/remove |
| `devices.yaml` | Mutable device inventory (flat map) | Any `add-devices`, `update-devices`, or `remove-devices` run |

`snmp-base.yaml` uses the ktranslate `@`-include syntax:
```yaml
devices:
  "@devices.yaml"
global:
  poll_time_sec: 300
  timeout_ms: 5000
  retries: 0
  mibs_enabled:
    - IF-MIB
    - PowerNet-MIB_UPS     # union of all devices' discovered_mibs
```

`devices.yaml` is a flat device map keyed by the current `device_name` value:
```yaml
ups_snmpv2c:
  device_name: ups_snmpv2c
  device_ip: 10.10.0.201
  snmp_comm: public
  oid: .1.3.6.1.4.1.318.1.3.27
  mib_profile: apc_ups.yml
  provider: kentik-ups
  poll_time_sec: 120
  user_tags:
    owning_team: dc_ops

ping_only:
  device_name: ping_only
  device_ip: 10.10.0.220
  provider: kentik_ping
  ping_only: true
  ping_interval_sec: 5
  user_tags:
    owning_team: load_balancing
```

Both files are mounted into the container at the root (`/snmp-base.yaml` and `/devices.yaml`) so the `@`-include resolves correctly.

Because the YAML key tracks `device_name`, `update-devices` can safely support renames while still matching the existing entry by immutable `device_ip`.

### No Autodiscovery in Production
Per project requirements, **autodiscovery is never enabled in production containers**. All network devices must be explicitly provided via the `devices` parameter. The production `snmp-base.yaml` never contains a `discovery:` section.

The pipeline supports **opt-in device probing** (`probeDevices=true`) which runs a separate, temporary ktranslate container to fingerprint devices (retrieve `sysObjectID`, match vendor profiles, confirm MIBs). The temporary container exits automatically and is cleaned up before the production container starts.

### Polling Container Restarts on Every Config Change
Any `add-devices`, `update-devices`, or `remove-devices` run always restarts the polling container after uploading updated config files. ktranslate does not hot-reload config; a restart is required to pick up inventory changes.

### One Container Per Pipeline Run
Each pipeline execution manages exactly one container. To deploy to multiple hosts, trigger separate pipeline runs with different `containerID` and `targetHost` values.

---

## Repository Structure

```
New Relic/
├── .claude/
│   └── CLAUDE.md                             # Project overview and requirements
├── README.md                                  # Setup guide and usage instructions
├── .gitignore
│
├── docs/
│   └── architecture.md                       # This file
│
├── newrelic/
│   └── newrelic-workflow.yml                 # New Relic Workflow Automation trigger template
│
├── pipelines/
│   ├── manage-container.yml                  # Master router — Validate + conditional template routing
│   ├── actions/
│   │   ├── create.yml                        # Stages: GenerateConfig → ProbeDevices (opt-in) → Deploy
│   │   ├── add-devices.yml                  # Stages: ProbeDevices (opt-in) → AddDevices
│   │   ├── update-devices.yml               # Stage:  UpdateDevices
│   │   ├── remove-devices.yml               # Stage:  RemoveDevices
│   │   ├── start.yml                         # Stage:  Deploy (start — reuses on-disk config)
│   │   └── stop-remove.yml                  # Stage:  Deploy (stop or remove)
│   └── templates/
│       └── steps/
│           ├── install-python-deps.yml       # pip install pyyaml for PythonScript@0 tasks
│           ├── copy-scripts-to-host.yml     # CopyFilesOverSSH: manage-container.sh + healthcheck.sh
│           ├── backup-config.yml            # SSH: cp devices.yaml + snmp-base.yaml → .bak
│           ├── upload-config.yml            # CopyFilesOverSSH: devices.yaml + snmp-base.yaml
│           ├── restart-and-healthcheck.yml  # SSH: restart container + run healthcheck.sh
│           ├── fetch-devices-b64.yml        # SSH: base64-encode devices.yaml → output variable
│           ├── validate-config.yml          # PythonScript@0: YAML structural validation on runner
│           ├── validate-fetched-devices.yml # PythonScript@0: validate host-fetched devices.yaml
│           └── publish-result-to-nr.yml     # PythonScript@0: pipeline result to New Relic Logs API
│
├── scripts/
│   ├── lib/
│   │   └── device_utils.py                   # Shared Python: build_device_entry, write YAML helpers
│   ├── generate_config.py                    # Generates snmp-base.yaml + devices.yaml (runs on runner)
│   ├── generate_probe_config.py              # Generates ktranslate discovery YAML for probing (runs on runner)
│   ├── manage_devices.py                     # Add/update/remove devices with IP-based merge + mibs_enabled refresh (runs on runner)
│   ├── merge_probe_results.py                # Merges probe discovery output into device configs (runs on runner)
│   ├── validate_inputs.py                    # Validates pipeline input parameters (runs on runner)
│   ├── validate_config.py                    # YAML structural validation wrapper (runs on runner)
│   ├── validate_fetched_devices.py           # Validates host-fetched devices.yaml (runs on runner)
│   ├── publish_result_to_nr.py               # Posts pipeline result to New Relic Logs API (runs on runner)
│   ├── render_template.py                    # Template rendering for docker-compose (runs on runner)
│   ├── run-probe.sh                          # Runs temp ktranslate discovery container (runs on host, pure bash)
│   ├── manage-container.sh                   # Container lifecycle: create, restart, start, stop, remove (runs on host)
│   └── healthcheck.sh                        # Post-deploy container health verification (runs on host)
│
└── templates/
    ├── docker-compose.template.yml           # Docker Compose template (parameterized by containerID)
    ├── snmp-base.template.yaml               # SNMP global config template
    └── devices.template.yaml                 # Empty device inventory template
```

---

## Pipeline Parameters

The pipeline (`pipelines/manage-container.yml`) accepts the following parameters via the Azure DevOps REST API `templateParameters` field:

| Parameter | Required For | Default | Description |
|-----------|-------------|---------|-------------|
| `containerAction` | All | — | `create`, `add-devices`, `update-devices`, `remove-devices`, `start`, `stop`, or `remove` |
| `containerID` | All | — | Unique container identifier (e.g., `npm-datacenter-01`) |
| `targetHost` | All | — | Azure DevOps SSH service connection name (e.g., `ssh-datacenter-01`) |
| `devices` | create, add-devices, update-devices | `[]` | JSON array of device objects to add or patch |
| `removeDevices` | remove-devices | `[]` | JSON array of device objects to remove (matched by `device_ip`) |
| `snmpCommunity` | No | `public` | Default SNMP community string |
| `probeDevices` | No | `false` | Auto-probe devices for sysOID/profile via temp container (opt-in for `create`/`add-devices`; rejected for `update-devices`) |
| `force` | No | `false` | Allow `create` to overwrite an existing container (backs up existing config before overwriting) |

### Devices JSON Format

**Field reference:**

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `device_name` | Yes | string | Human-readable device name. Used as the key in devices.yaml. Must be unique. |
| `device_ip` | Yes | string | Device IPv4 address. Used as the SNMP polling target and **deduplication key**. |
| `snmp_comm` | * | string | SNMPv2c community string. Required unless `snmp_v3` is provided. |
| `snmp_v3` | * | object | SNMPv3 credentials object. Required unless `snmp_comm` is provided. |
| `mib_profile` | ** | string | Kentik vendor profile filename (e.g., `cisco-catalyst.yml`). Auto-detected if `probeDevices=true`. |
| `oid` | ** | string | sysObjectID (e.g., `.1.3.6.1.4.1.318.1.3.27`). Auto-detected if `probeDevices=true`. |
| `provider` | ** | string | Device type label (e.g., `kentik-switch`). Auto-detected if `probeDevices=true`. |
| `user_tags` | No | map | Custom key-value attributes forwarded to New Relic (e.g., `{owning_team: dc_ops}`). |
| `ping_only` | No | boolean | Disables SNMP polling and enables RTT polling for this device. When using this mode, provide `provider: kentik_ping`. |
| `ping_interval_sec` | No | integer | Positive per-device override for the default 1 packet/sec RTT polling rate used by `ping_only` / response-time polling. |
| `poll_time_sec` | No | integer | Positive per-device override for the container-level `global.poll_time_sec` setting in `snmp-base.yaml`. |
| `description` | No | string | Free-text description or sysDescr. Auto-detected if `probeDevices=true`. |
| `discovered_mibs` | No | array | MIBs confirmed to be supported by this device. Auto-detected if `probeDevices=true`. |

\* Either `snmp_comm` or `snmp_v3` is required (not both).  
\** Optional, but strongly recommended when `probeDevices=false`, and auto-detected when `probeDevices=true`.

**Minimal SNMPv2c example (probeDevices=true):**
```json
[
  {
    "device_name": "switch-floor-01",
    "device_ip": "10.0.1.1",
    "snmp_comm": "public"
  }
]
```

**Full example with user_tags (probeDevices=false):**
```json
[
  {
    "device_name": "ups_snmpv2c",
    "device_ip": "10.10.0.201",
    "snmp_comm": "public",
    "oid": ".1.3.6.1.4.1.318.1.3.27",
    "mib_profile": "apc_ups.yml",
    "provider": "kentik-ups",
    "poll_time_sec": 120,
    "discovered_mibs": ["PowerNet-MIB_UPS", "UPS-MIB"],
    "user_tags": {
      "owning_team": "dc_ops"
    }
  },
  {
    "device_name": "vip-lb-01",
    "device_ip": "10.10.0.220",
    "provider": "kentik_ping",
    "ping_only": true,
    "ping_interval_sec": 5,
    "user_tags": {
      "owning_team": "load_balancing"
    }
  }
]
```

**removeDevices example (only device_ip is required):**
```json
[
  { "device_ip": "10.0.1.1" },
  { "device_ip": "10.0.1.2" }
]
```

**SNMPv3 credentials:**
```json
{
  "device_name": "fw-01",
  "device_ip": "10.0.1.10",
  "snmp_v3": {
    "user_name": "snmpuser",
    "authentication_protocol": "SHA",
    "authentication_passphrase": "authpass",
    "privacy_protocol": "AES",
    "privacy_passphrase": "privpass",
    "context_engine_id": "80:00:01:01:0a:14:1e:28",
    "context_name": "core-routing"
  }
}
```

**`snmp_v3` field reference:**

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `user_name` | Yes | string | SNMPv3 user name. |
| `authentication_protocol` | Yes | string | Must be one of `NoAuth`, `MD5`, or `SHA`. |
| `authentication_passphrase` | No* | string | Authentication passphrase. |
| `privacy_protocol` | Yes | string | Must be one of `NoPriv`, `DES`, `AES`, `AES192`, `AES256`, `AES192C`, or `AES256C`. |
| `privacy_passphrase` | No* | string | Privacy passphrase. |
| `context_engine_id` | No | string | SNMPv3 context engine ID. |
| `context_name` | No | string | SNMPv3 context name. |

\* `authentication_passphrase` is required when `authentication_protocol` is not `NoAuth`. `privacy_passphrase` is required when `privacy_protocol` is not `NoPriv`.

### `update-devices` semantics

`update-devices` uses the same `devices` payload shape, but each object is treated as a patch instead of a full replacement.

- `device_ip` is **required** and is used only to match an existing entry.
- Omitted fields are preserved from the fetched `devices.yaml` entry.
- Supplied fields overwrite the existing value.
- `device_name` may be supplied to rename both the stored field and the top-level YAML key.
- `device_ip` may not change. To move a device to a new IP, add the replacement device and then remove the old one.
- If `snmp_v3` is supplied, it must contain the full final desired SNMPv3 object for that device (supplying/updating individual v3 fields is not supported). Nested SNMPv3 fields are replaced, not merged, so any optional fields you want to keep must be included again. The object must also include the required SNMPv3 fields listed above.

Expected update failures:
- unknown `device_ip`
- duplicate `device_ip` targets in the request
- `device_name` collisions after rename
- invalid field types or values
- partial `snmp_v3` objects

---

## Pipeline Architecture

### Template Structure

The pipeline is split across two layers:

**Master pipeline** (`pipelines/manage-container.yml`):
- Defines all parameters and the `Validate` stage (runs for every action)
- Routes to the correct action template via `${{ if eq(parameters.containerAction, '...') }}` stage insertions
- Registers as a single pipeline in Azure DevOps — the pipeline ID is unchanged

**Action templates** (`pipelines/actions/`):
- Each file owns the stages for one logical action
- All stages `dependsOn: Validate` (defined in the master pipeline)
- Parameters are explicitly declared and passed through from the master

**Step templates** (`pipelines/templates/steps/`):
- Reusable building-block steps shared across action templates
- Each encapsulates one repeatable SSH or SCP operation

| Step template | Purpose | Used by |
|---------------|---------|---------|
| `install-python-deps.yml` | Installs Python dependencies (`pyyaml`) on the runner before any `PythonScript@0` tasks | create, add-devices, update-devices, remove-devices |
| `copy-scripts-to-host.yml` | SCP `manage-container.sh` + `healthcheck.sh` to host | create, add-devices, update-devices, remove-devices, start, stop-remove |
| `validate-config.yml` | YAML structural validation on the runner before any config is copied to a host | create, add-devices, update-devices, remove-devices |
| `validate-fetched-devices.yml` | Validates the host-fetched `devices.yaml` before merge/update/remove work begins | add-devices, update-devices, remove-devices |
| `backup-config.yml` | SSH: create `.bak` copies of config files before overwrite | add-devices, update-devices, remove-devices |
| `upload-config.yml` | SCP updated `devices.yaml` + `snmp-base.yaml` to host | add-devices, update-devices, remove-devices |
| `restart-and-healthcheck.yml` | SSH: restart container, then health check | add-devices, update-devices, remove-devices |
| `fetch-devices-b64.yml` | SSH: base64-encode `devices.yaml` into output variable | add-devices, update-devices, remove-devices |
| `publish-result-to-nr.yml` | POST pipeline result (`action`, `containerID`, `targetHost`, `result`, `details`, `requestedBy`, `pipelineRunId`, `pipelineRunUrl`, `source`, `service`) to New Relic Logs API | create, add-devices, update-devices, remove-devices, start, stop-remove |

---

## Pipeline Stages Detail

### Validate *(all actions — inline in master)*
- Checks all required parameters are present (`containerID`, `targetHost`)
- For `create` and `add-devices`: validates `devices` is a non-empty JSON array; checks each entry has `device_ip` and `device_name`
- For `update-devices`: validates `devices` is a non-empty JSON array; requires `device_ip`, allows partial objects, rejects duplicate target IPs, and requires a full `snmp_v3` object if present
- For `remove-devices`: validates `removeDevices` is a non-empty JSON array; checks each entry has `device_ip`
- Fails fast before any host changes are made

### GenerateConfig *(create only — `actions/create.yml`)*
- Runs `scripts/generate_config.py` on the Microsoft-hosted cloud runner
- Generates `devices.yaml` (flat device map) and `snmp-base.yaml` (with `devices: "@devices.yaml"` @-include) from the `devices` JSON parameter
- Generates `docker-compose.yml` by replacing `{{CONTAINER_ID}}` in the template
- Computes initial `mibs_enabled` as the union of IF-MIB + all devices' `discovered_mibs`
- Publishes config files as a pipeline artifact (`container-config`) for the Deploy stage

### ProbeDevices *(opt-in, create and add-devices — `actions/create.yml` and `actions/add-devices.yml`)*
- **Only runs when `probeDevices=true`**
- **No Python, pyyaml, or jq required on any target host** — all processing stays on the runner
- **Step 1 (runner):** Runs `scripts/generate_probe_config.py` → generates `snmp-probe.yaml` with `/32` CIDRs per device IP
- **Step 2 (SCP to host):** Copies `snmp-probe.yaml` and `run-probe.sh` to `/etc/ktranslate/probe-{containerID}/`
- **Step 3 (host, pure bash):** Runs `run-probe.sh` — uses `timeout docker run --rm` with `-snmp_out_file /work/discovered-snmp.yaml` to write discovery results to a scratch file. Container self-cleans on exit via `--rm`.
- **Step 4 (host → runner):** Encodes `discovered-snmp.yaml` as base64 → pipeline output variable → probe directory cleaned up
- **Step 5 (runner):** Decodes the YAML, merges enriched fields into the caller's device list (user-provided values always win); for `create` publishes a `container-config-enriched` artifact with the final deployable config; for `add-devices` publishes a `probe-enriched` artifact with the enriched devices JSON
- **Timeout:** 15 minutes for the job; 120 seconds for the probe container itself. Devices that fail to probe keep their original values.

### Deploy *(create — `actions/create.yml`)*
- **Pre-flight check**: Verifies `/etc/ktranslate/{containerID}/` does not already exist on the host
  - If it exists and `force=false` (default): pipeline **fails fast** with an error message suggesting `add-devices`, `remove`, or `force=true`
  - If it exists and `force=true`: backs up all existing config files with a UTC timestamp suffix before overwriting
- Downloads `container-config` when probing is skipped, or `container-config-enriched` when probing succeeds, then deploys `snmp-base.yaml`, `devices.yaml`, `docker-compose.yml` to host
- Copies management scripts via `copy-scripts-to-host` step template
- Runs `manage-container.sh --action create` on host (docker-compose up)
- Health check via `healthcheck.sh`
- Publishes result to New Relic Logs API via `publish-result-to-nr` step template

### AddDevices *(`actions/add-devices.yml`)*
- Fetches current `devices.yaml` from host as base64 (via `fetch-devices-b64` step template)
- If `probeDevices=true`, reads enriched devices JSON from `probe-enriched` artifact; otherwise uses raw caller-supplied `devices` JSON
- Runs `scripts/manage_devices.py --action add` on the runner:
  - For each new device: checks if `device_ip` already exists in `devices.yaml`
    - **If exists → skip and log a warning** (no pipeline failure)
    - If new → append to the device map
  - Regenerates `mibs_enabled` in `snmp-base.yaml` as the union of **all** devices' `discovered_mibs`
- Backs up, uploads, and restarts via `backup-config`, `upload-config`, `copy-scripts-to-host`, and `restart-and-healthcheck` step templates
- Publishes result to New Relic Logs API via `publish-result-to-nr` step template

### UpdateDevices *(`actions/update-devices.yml`)*
- Fetches current `devices.yaml` from host as base64 (via `fetch-devices-b64` step template)
- Runs `scripts/manage_devices.py --action update` on the runner:
  - For each update object: finds the matching entry by immutable `device_ip`
  - Applies only the supplied fields and preserves omitted fields
  - Renames the YAML key if `device_name` changes
  - Rejects unknown `device_ip` targets and `device_name` collisions before writing
  - Regenerates `mibs_enabled` in `snmp-base.yaml` after the final patched inventory is built
- Backs up, uploads, and restarts via `backup-config`, `upload-config`, `copy-scripts-to-host`, and `restart-and-healthcheck` step templates
- Publishes result to New Relic Logs API via `publish-result-to-nr` step template

### RemoveDevices *(`actions/remove-devices.yml`)*
- Fetches current `devices.yaml` from host as base64 (via `fetch-devices-b64` step template)
- Runs `scripts/manage_devices.py --action remove` on the runner:
  - For each entry in `removeDevices`: finds the matching key by `device_ip` and deletes it
    - **If `device_ip` not found → log a warning** (no pipeline failure)
  - Regenerates `mibs_enabled` in `snmp-base.yaml` (scan remaining devices; remove MIBs that no remaining device uses)
- Backs up, uploads, and restarts via `backup-config`, `upload-config`, `copy-scripts-to-host`, and `restart-and-healthcheck` step templates
- Publishes result to New Relic Logs API via `publish-result-to-nr` step template

### Deploy — start *(`actions/start.yml`)*
- Copies management scripts via `copy-scripts-to-host` step template
- Runs `manage-container.sh --action start` on host:
  - Validates all required config files are present on disk (`snmp-base.yaml`, `devices.yaml`, `docker-compose.yml`, `.env`)
  - Validates the stopped Docker container still exists
  - If the container is already running, exits cleanly with a warning (idempotent)
  - Runs `docker start` on the preserved container — no image pull, no config regeneration, no container recreation
- Health check via `healthcheck.sh`
- Publishes result to New Relic Logs API via `publish-result-to-nr` step template

### Deploy — stop / remove *(`actions/stop-remove.yml`)*
- Copies management scripts via `copy-scripts-to-host` step template
- **stop**: Runs `manage-container.sh --action stop` on host (stops the running container but preserves both the Docker container and `/etc/ktranslate/{containerID}/`)
- **remove**: Runs `manage-container.sh --action remove` on host (stops the container if needed, removes it from Docker, then deletes `/etc/ktranslate/{containerID}/`)
- Publishes result to New Relic Logs API via `publish-result-to-nr` step template

---

## Container Lifecycle Actions

### create
Creates a new container on the specified host with an initial device list.

```
containerAction=create
containerID=npm-dc01-01
targetHost=ssh-datacenter-01
devices=[...]
probeDevices=true   # optional
```

Result: Container `ktranslate-npm-dc01-01` running. `snmp-base.yaml` + `devices.yaml` deployed to `/etc/ktranslate/npm-dc01-01/`.

### add-devices
Appends new devices to `devices.yaml` for an existing container, restarts the poller.

```
containerAction=add-devices
containerID=npm-dc01-01
targetHost=ssh-datacenter-01
devices=[... new devices ...]
probeDevices=true   # optional
```

- Devices with an IP that already exists in `devices.yaml` are **skipped with a warning**
- All new devices are appended; `mibs_enabled` is refreshed
- Polling container is restarted

### update-devices
Patches existing devices in `devices.yaml` by `device_ip`, then restarts the poller.

```
containerAction=update-devices
containerID=npm-dc01-01
targetHost=ssh-datacenter-01
devices=[{"device_ip":"10.0.1.50","device_name":"ap-lobby-renamed","description":"Lobby AP refreshed"}]
```

- `device_ip` is the immutable match key
- Omitted fields are preserved; supplied fields overwrite current values
- `device_name` renames the YAML key
- `device_ip` changes must be handled as add + remove
- Polling container is restarted

### remove-devices
Removes specified devices from `devices.yaml` by `device_ip`, restarts the poller.

```
containerAction=remove-devices
containerID=npm-dc01-01
targetHost=ssh-datacenter-01
removeDevices=[{"device_ip":"10.0.1.1"},{"device_ip":"10.0.1.2"}]
```

- Device IPs not found in `devices.yaml` are **skipped with a warning**
- `mibs_enabled` is refreshed to reflect only MIBs used by remaining devices
- Polling container is restarted

### start
Starts a previously stopped container using the config files already on disk. No config regeneration or image pull is performed.

```
containerAction=start
containerID=npm-dc01-01
targetHost=ssh-datacenter-01
```

Requires all config files to be present in `/etc/ktranslate/{containerID}/` (i.e., the container must have been created and only stopped, not removed). If the container is already running, the action exits cleanly. If config files are missing, the pipeline fails with an actionable error.

### stop
Stops the running container (keeps all config files on host).

```
containerAction=stop
containerID=npm-dc01-01
targetHost=ssh-datacenter-01
```

### remove
Stops the container and deletes all config files from the host.

```
containerAction=remove
containerID=npm-dc01-01
targetHost=ssh-datacenter-01
```

---

## File Locations on Target Linux Hosts

```
/etc/ktranslate/
├── {containerID}/
│   ├── snmp-base.yaml          # Stable global config (backed up to .bak on add/update/remove)
│   ├── devices.yaml            # Mutable device inventory (backed up to .bak on add/update/remove)
│   └── docker-compose.yml      # Container definition
└── scripts/
    ├── manage-container.sh     # Lifecycle: create, restart, start, stop, remove (copied by pipeline)
    ├── healthcheck.sh          # Health verification (copied by pipeline)
    └── run-probe.sh            # Device probing — pure bash (copied by ProbeDevices stage)
```

Docker container name: `ktranslate-{containerID}`

---

## containerID Naming Convention

The `containerID` is the primary key that identifies a container across all pipeline operations.

**Recommended pattern:** `npm-{location}-{seq}`

Examples:
- `npm-datacenter-01` — first NPM container in a datacenter
- `npm-office-nyc-01` — first NPM container in the NYC office
- `npm-event-lv-01` — temporary event container in Las Vegas

**Rules:**
- Must be unique across all hosts you manage
- Use only lowercase letters, numbers, and hyphens (Docker container name constraint)
- The caller must track which `containerID` lives on which `targetHost` (see [Stateless Design](#stateless-design))

---

## probeDevices — How It Works

When `probeDevices=true`, a temporary `ktranslate` container is used to SNMP-fingerprint each device before the production container starts. The probe uses `-snmp_out_file` to write results to a separate scratch file (no mutation of production config). The container runs with `docker run --rm` and a `timeout` wrapper — it self-cleans on exit.

### Recommended use when probeDevices=false
Per the [New Relic NPM manual add guide](https://docs.newrelic.com/docs/network-performance-monitoring/get-started/network-monitoring-best-practices/#man-device-add), when not using auto-discovery, all device fields must be provided manually:

```json
{
  "device_name": "ups_snmpv2c",
  "device_ip": "10.10.0.201",
  "snmp_comm": "public",
  "oid": ".1.3.6.1.4.1.318.1.3.27",
  "mib_profile": "apc_ups.yml",
  "provider": "kentik-ups",
  "discovered_mibs": ["PowerNet-MIB_UPS", "UPS-MIB"],
  "user_tags": { "owning_team": "dc_ops" }
}
```

Without `oid` and `mib_profile`, devices will still be polled (using IF-MIB), but with reduced telemetry.

---

## Security Notes

### Required Service Connections
| Name | Type | Purpose |
|------|------|---------|
| `ssh-{host-name}` | SSH | One per physical Linux host (e.g., `ssh-datacenter-01`) |

**SSH key strategy:** Use a single SSH key pair. Distribute the public key to all hosts' `authorized_keys`. Reuse the same private key across all SSH service connections.

### Variable Group: `newrelic-npm-secrets`
| Variable | Secret | Description |
|----------|--------|-------------|
| `NR_INGEST_KEY` | Yes | New Relic API key passed to ktranslate |
| `NR_ACCOUNT_ID` | Yes | New Relic account ID |

### Pipeline Registration
- One registered pipeline: `pipelines/manage-container.yml` (the master router)
- Action templates in `pipelines/actions/` and step templates in `pipelines/templates/steps/` are referenced internally; they do not need separate pipeline registrations
- Source: Azure DevOps Repos (built-in)
- No git-push triggers — API-triggered only (`trigger: none`)

### Credential Handling
- No secrets stored in the Azure DevOps repository
- SSH private key stored only in Azure DevOps service connections
- NR API key and Account ID stored only in Azure DevOps variable group (masked in logs)
- Azure DevOps service principal credentials stored only in New Relic Workflow Automation secrets
- Deployment user on hosts needs only `docker` group membership (no root)

---

## New Relic Workflow Automation Setup

### API Call Structure

The shipped workflow in [newrelic/newrelic-workflow.yml](newrelic/newrelic-workflow.yml) performs the trigger in three steps:

1. `getAzureToken` uses `http.post` to request an OAuth 2.0 bearer token from Azure AD.
2. `triggerPipeline` uses `http.post` to call the Azure DevOps Pipelines Runs API with that bearer token.
3. `logTriggerResult` writes a workflow-trigger log to New Relic with the HTTP status codes and queued run metadata.

The Azure AD service principal credentials (`clientId`, `clientSecret`, `tenantId`) stay in New Relic Secrets and are injected into the workflow at runtime.

The underlying REST call it makes:

```
POST https://dev.azure.com/{org}/{project}/_apis/pipelines/{pipelineId}/runs?api-version=7.1

Headers:
  Content-Type: application/json
  Authorization: Bearer {OAuth2 access token — obtained from Azure AD using service principal credentials}

Body:
{
  "resources": {
    "repositories": {
      "self": { "refName": "refs/heads/main" }
    }
  },
  "templateParameters": {
    "containerAction": "create",
    "containerID": "npm-dc01-01",
    "targetHost": "ssh-datacenter-01",
    "devices": "[{\"device_name\":\"switch-01\",\"device_ip\":\"10.0.1.1\",\"snmp_comm\":\"public\"}]",
    "snmpCommunity": "public",
    "probeDevices": "true",
    "force": "false"
  }
}
```

### Workflow Trigger Options
- **Manual**: Via New Relic UI or `StartWorkflowRun` NerdGraph API
- **Alert-based**: Triggered when NR detects an alert condition
- **Scheduled**: Cron expression for recurring runs

### Pipeline Execution Logging

There are two separate log streams:

- **Workflow trigger logs** are emitted by `logTriggerResult` in [newrelic/newrelic-workflow.yml](newrelic/newrelic-workflow.yml). They capture `containerAction`, `containerID`, `targetHost`, `tokenStatusCode`, `pipelineStatusCode`, `pipelineRunId`, and `pipelineRunUrl` immediately after the queue request.
- **Pipeline result logs** are emitted by [pipelines/templates/steps/publish-result-to-nr.yml](pipelines/templates/steps/publish-result-to-nr.yml) via [scripts/publish_result_to_nr.py](scripts/publish_result_to_nr.py). They capture `action`, `containerID`, `targetHost`, `result`, `details`, `pipelineRunId`, `pipelineRunUrl`, `requestedBy`, `source = 'azure-devops-pipeline'`, and `service = 'npm-container-management'`.

The pipeline result step uses `condition: always()` within each action job, so action-job failures still emit a result log. However, failures in the top-level `Validate` stage happen before any action job starts and therefore do not emit the `source = 'azure-devops-pipeline'` result log.

---

## Host Prerequisites

Target Linux hosts require:
- **Docker** and the `docker-compose` CLI available on the host
- **No Python required** — all Python processing runs on the Microsoft-hosted pipeline runner

The deployment user (`azpipeline`) needs only `docker` group membership — no root or sudo access required.

---

## Common Operations Reference

### Spin up a new container with auto-probing
```
containerAction=create, containerID=<new-id>, targetHost=<ssh-conn>, devices=[...], probeDevices=true
```
Users only need `device_name`, `device_ip`, and `snmp_comm` — the pipeline auto-detects `oid`, `mib_profile`, and supported MIBs.

### Spin up a new container (manual profiles)
```
containerAction=create, containerID=<new-id>, targetHost=<ssh-conn>, devices=[... full fields ...]
```

### Add new devices to an existing container
```
containerAction=add-devices, containerID=<existing-id>, targetHost=<ssh-conn>, devices=[... new devices only ...]
```
Only provide the new devices to add — the pipeline fetches the current `devices.yaml` from the host and appends. Duplicate IPs are skipped with a warning.

### Update existing devices in place
```
containerAction=update-devices, containerID=<existing-id>, targetHost=<ssh-conn>, devices=[... patch objects with device_ip ...]
```
Only provide the fields you want to change. `device_ip` stays immutable; use add + remove for IP changes.

### Remove one or more devices
```
containerAction=remove-devices, containerID=<existing-id>, targetHost=<ssh-conn>,
removeDevices=[{"device_ip":"10.0.1.1"},{"device_ip":"10.0.1.2"}]
```

### Stop a container temporarily
```
containerAction=stop, containerID=<id>, targetHost=<ssh-conn>
```

### Restart a stopped container
```
containerAction=start, containerID=<id>, targetHost=<ssh-conn>
```
Reuses the config files already on disk — no device list required.

### Permanently remove a container
```
containerAction=remove, containerID=<id>, targetHost=<ssh-conn>
```

---

## Future Concurrency Management

The pipeline currently has no cross-run concurrency control for a specific mutable target such as a single `{targetHost, containerID}` pair. As a result, multiple runs can fetch the same on-host snapshot, generate different replacement files, and upload them back in an unpredictable order.

### Current behavior without concurrency control

Across all actions, the current behavior is effectively **first fetch wins locally, last writer wins on the host** whenever two or more runs target the same container at the same time.

| Action | Current concurrent behavior without a lock |
|--------|--------------------------------------------|
| `create` | Two runs can both pass pre-flight checks before either creates the directory/container. The later run can overwrite config written by the earlier run or fail mid-flight depending on timing. |
| `add-devices` | Two or more runs can fetch the same `devices.yaml`, independently append different devices, and upload full-file replacements. The last upload wins; earlier additions can be lost. |
| `update-devices` | Two or more runs can patch the same stale fetched snapshot and upload conflicting full-file replacements. A later upload can silently discard fields changed by an earlier run. |
| `remove-devices` | Concurrent removals can reintroduce devices or remove the wrong final set if each run writes from a different stale snapshot. |
| `start` | Concurrent `start` runs are mostly benign because the action is intended to be idempotent, but they can still overlap with `stop`, `remove`, or config-mutating actions and cause inconsistent lifecycle sequencing. |
| `stop` | Concurrent `stop` with `start`, `create`, or config-mutating actions can produce non-deterministic final container state depending on which lifecycle command completes last. |
| `remove` | Concurrent `remove` with any other action is high risk because it can delete the container directory while another run is fetching, uploading, or restarting it. |

Polling-container restarts amplify this race: multiple mutating runs can each upload a different config and then restart the same container in sequence, leaving the final runtime state dependent on whichever run finishes last.

### Required state

To serialize work safely, the pipeline needs a stable concurrency identity for each mutable target. At minimum:

| Field | Type | Purpose |
|-------|------|---------|
| `containerID` | string | Primary logical identity of the managed container |
| `targetHost` | string | Distinguishes identical `containerID` values across hosts and identifies the actual mutation target |
| `concurrencyKey` | string | Canonical lock key derived from the target, for example `npm/{targetHost}/{containerID}` |
| `actionClass` | string | Classifies whether the action is inventory-mutating, lifecycle-only, or destructive, enabling future policy decisions |
| `lastKnownRevision` | string | Optional hash/version of the fetched host config for optimistic concurrency checks before upload |
| `lockOwnerRunId` | string | Optional active pipeline run identifier for debugging, audit, or external lock recovery |

Only the first three fields are strictly required to introduce sequential queueing. The revision and ownership fields enable stronger defense-in-depth if the design later adds host-side or storage-backed compare-and-swap validation.

### Benefits

Introducing target-scoped concurrency control would provide:

1. **Deterministic sequencing** — only one run mutates a given container at a time.
2. **No silent lost updates** — `add-devices`, `update-devices`, and `remove-devices` no longer race to replace the same files.
3. **Safer destructive actions** — `remove` cannot delete files while another run is fetching or restarting the same container.
4. **Clear operational auditability** — queued and active runs can be tied to a single protected target.
5. **Better scalability** — different containers can still run in parallel as long as they do not share the same concurrency key.

### Recommended implementation

The recommended Azure DevOps-native solution is to convert host-mutating work into **deployment jobs** that target an **environment/resource** protected by an **Exclusive lock** check, with YAML `lockBehavior: sequential`.

Recommended design:

1. Create an Azure DevOps environment (or environment resource) that represents the mutable target scope.
2. Use a target-scoped identity such as `{targetHost}.{containerID}` so locking is per container, not global across the whole pipeline.
3. Move the mutating action jobs (`create`, `add-devices`, `update-devices`, `remove-devices`, `start`, `stop`, `remove`) into deployment jobs that target that environment/resource.
4. Enable **Exclusive lock** on the environment/resource in Azure DevOps.
5. Set `lockBehavior: sequential` so queued runs execute one-by-one instead of `runLatest`, which would cancel older queued runs.

This approach is preferred because it is Azure-native, auditable, and purpose-built for serializing deployment-style stages. It also avoids over-serializing unrelated work when the protected resource is scoped per container.

### Recommended defense-in-depth

Exclusive locking should be the primary control, but the strongest final design would also keep a lower-level safety check:

- compute a revision/hash from the fetched `devices.yaml` and/or `snmp-base.yaml`
- verify the revision is unchanged immediately before upload
- fail fast if another run changed the target between fetch and write

That additional optimistic concurrency check would protect the host state even if a run bypasses the intended pipeline path or if locking is misconfigured.

---

## Future State Management

This pipeline is currently **stateless by design** for pipeline execution — state management could be added for a future architecture phase. Device inventory state is maintained on the host filesystem.

### Required State Per Container

A future state store (i.e: **Azure Blob Storage**, one JSON blob per container) could track:

| Field | Type | Purpose |
|-------|------|---------|
| `containerID` | string | Primary key |
| `targetHost` | string | Enables `add-devices`/`update-devices`/`stop`/`remove` without re-specifying the host |
| `status` | string | `running`, `stopped`, `removed` |
| `snmpCommunity` | string | Current default community string |
| `createdAt` | ISO 8601 | When the container was first created |
| `updatedAt` | ISO 8601 | When devices.yaml was last modified |

### Benefits of State Management

With state, the pipeline could:
1. **Auto-resolve `targetHost`** — users only need `containerID` for all operations
2. **Validate actions** — prevent adding devices to a stopped container
3. **Provide discoverability** — list all managed containers and their status
4. **Maintain audit trail** — track who changed what and when

### Recommended Implementation
- **Storage:** Azure Blob Storage (one JSON blob per container in a `container-state` blob container)
- **Auth:** Azure Resource Manager service connection in Azure DevOps
- **Operations:** `az storage blob download/upload` via `AzureCLI@2` task


**Recommended future improvement:**
- Retrieve credentials at container startup via a sidecar or init script
- Alternatively, use Docker secrets or environment-variable-based credential injection
- This would eliminate plaintext credential storage on the host filesystem

**Current mitigations:**
- `devices.yaml` and `snmp-base.yaml` are uploaded with mode `644` and mounted read-only into the container
- Host access is restricted to authorized SSH service connections
- Credentials are not logged in pipeline output (masked by Azure DevOps variable groups)