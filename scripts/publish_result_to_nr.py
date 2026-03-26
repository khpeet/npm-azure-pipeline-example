#!/usr/bin/env python3
"""publish_result_to_nr.py — Publish pipeline result to New Relic Logs API.

Runs on pipeline runner.
Replaces the bash step in publish-result-to-nr.yml that built JSON + used curl.

Sanitizes sensitive inputs, constructs a JSON payload, and
POSTs it to the New Relic Log API for execution tracking and audit logging.

Usage (Azure Pipeline — PythonScript@0):
  - task: PythonScript@0
    inputs:
      scriptSource: filePath
      scriptPath: $(Build.SourcesDirectory)/scripts/publish_result_to_nr.py
    env:
      ACTION: ${{ parameters.action }}
      CONTAINER_ID: ${{ parameters.containerID }}
      TARGET_HOST: ${{ parameters.targetHost }}
      DETAILS_RAW: ${{ parameters.details }}
      AGENT_JOBSTATUS: $(Agent.JobStatus)
      NR_INGEST_KEY: $(NR_INGEST_KEY)
      BUILD_BUILDID: $(Build.BuildId)
      SYSTEM_COLLECTIONURI: $(System.CollectionUri)
      SYSTEM_TEAMPROJECT: $(System.TeamProject)
      BUILD_REQUESTEDFOR: $(Build.RequestedFor)
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error


# Regex matching sensitive YAML field names — values after these are redacted.
# Same pattern as the original sed expression in the bash step.
_SENSITIVE_INPUTS = re.compile(
    r'(snmp_comm|snmp_v3|community|auth_password|priv_password|'
    r'password|auth_key|priv_key)[^,;.]*',
    re.IGNORECASE,
)


def sanitise_details(raw: str) -> str:
    """Strip control chars, redact sensitive fields, truncate to 500 chars."""
    # Strip control characters (ASCII 0–31)
    cleaned = re.sub(r'[\x00-\x1f]', '', raw)
    # Redact sensitive field values
    cleaned = _SENSITIVE_INPUTS.sub(r'\1=[REDACTED]', cleaned)
    # Truncate
    return cleaned[:500]


def main():
    action = os.environ.get('ACTION', '')
    container_id = os.environ.get('CONTAINER_ID', '')
    target_host = os.environ.get('TARGET_HOST', '')
    details_raw = os.environ.get('DETAILS_RAW', '')
    agent_job_status = os.environ.get('AGENT_JOBSTATUS', '')
    nr_ingest_key = os.environ.get('NR_INGEST_KEY', '')
    build_id = os.environ.get('BUILD_BUILDID', '')
    collection_uri = os.environ.get('SYSTEM_COLLECTIONURI', '')
    team_project = os.environ.get('SYSTEM_TEAMPROJECT', '')
    requested_by = os.environ.get('BUILD_REQUESTEDFOR', '')

    # Determine result at runtime
    pipeline_result = 'success' if agent_job_status == 'Succeeded' else 'failure'

    safe_details = sanitise_details(details_raw)

    pipeline_run_url = f'{collection_uri}{team_project}/_build/results?buildId={build_id}'

    payload = [{
        'message': f'NPM Pipeline Result: {action} {pipeline_result}',
        'attributes': {
            'action': action,
            'containerID': container_id,
            'targetHost': target_host,
            'result': pipeline_result,
            'details': safe_details,
            'pipelineRunId': build_id,
            'pipelineRunUrl': pipeline_run_url,
            'requestedBy': requested_by,
            'source': 'azure-devops-pipeline',
            'service': 'npm-container-management',
        },
    }]

    payload_bytes = json.dumps(payload).encode('utf-8')

    req = urllib.request.Request(
        'https://log-api.newrelic.com/log/v1',
        data=payload_bytes,
        headers={
            'Api-Key': nr_ingest_key,
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req) as resp:
            http_code = resp.status
    except urllib.error.HTTPError as e:
        http_code = e.code
    except urllib.error.URLError as e:
        print(f'WARNING: Failed to publish result to New Relic: {e.reason}')
        # Non-fatal — don't fail the pipeline for audit logging issues
        return

    if 200 <= http_code < 300:
        print(f'Result published to New Relic (HTTP {http_code})')
    else:
        print(f'WARNING: Failed to publish result to New Relic (HTTP {http_code})')
        # Non-fatal — don't fail the pipeline for audit logging issues


if __name__ == '__main__':
    main()
