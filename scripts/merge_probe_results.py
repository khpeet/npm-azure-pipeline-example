#!/usr/bin/env python3
"""merge_probe_results.py — Merge probe-discovered data into device configs.

Runs on pipeline runner.

Two output modes:
  --output-mode config  (create flow)
      Writes full snmp-base.yaml + devices.yaml to --output-dir.
  --output-mode json    (add-devices flow)
      Writes enriched-devices.json to --output-dir for downstream merge via manage_devices.py.

Usage (Azure Pipeline — PythonScript@0):
  - task: PythonScript@0
    inputs:
      scriptSource: filePath
      scriptPath: $(Build.SourcesDirectory)/scripts/merge_probe_results.py
      arguments: >-
        --container-id $(containerID)
        --probe-yaml-path $(probeYamlPath)
        --output-dir $(outputDir)
        --output-mode config
    env:
      DEVICES_JSON: ${{ parameters.devices }}
      SNMP_COMMUNITY: ${{ parameters.snmpCommunity }}
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Allow importing lib modules when PYTHONPATH includes scripts/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.device_utils import (
    build_device_entry,
    compute_mibs_enabled,
    merge_probe_results,
    write_devices_yaml,
    write_snmp_base_yaml,
)


def main():
    parser = argparse.ArgumentParser(
        description='Merge probe-discovered data into device configs.'
    )
    parser.add_argument('--container-id', required=True,
                        help='Unique container identifier')
    parser.add_argument('--probe-yaml-path', required=True,
                        help='Path to discovered-snmp.yaml from probe run')
    parser.add_argument('--output-dir', required=True,
                        help='Directory to write output files')
    parser.add_argument('--output-mode', required=True, choices=['config', 'json'],
                        help='config: write full YAML configs; json: write enriched JSON only')
    parser.add_argument('--devices', default=None,
                        help='Original devices JSON array (or set DEVICES_JSON env var)')
    parser.add_argument('--snmp-community', default=None,
                        help='Default SNMP community string (or set SNMP_COMMUNITY env var)')
    args = parser.parse_args()

    # Resolve from args or environment variables
    devices_json = args.devices or os.environ.get('DEVICES_JSON', '[]')
    snmp_community = args.snmp_community or os.environ.get('SNMP_COMMUNITY', 'public')
    output_dir = args.output_dir.rstrip('/')

    original_devices = json.loads(devices_json)
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Read probe output
    with open(args.probe_yaml_path, encoding='utf-8') as f:
        discovered_content = f.read()

    # Merge using shared utility
    enriched = merge_probe_results(original_devices, discovered_content)

    os.makedirs(output_dir, exist_ok=True)

    if args.output_mode == 'config':
        # Build devices map and write full config files
        devices_dict = {}
        for device in enriched:
            name = device.get('device_name', 'unknown')
            entry = build_device_entry(device, snmp_community)
            devices_dict[name] = entry

        write_devices_yaml(f'{output_dir}/devices.yaml',
                           args.container_id, devices_dict, timestamp)
        mibs_enabled = compute_mibs_enabled(devices_dict)
        write_snmp_base_yaml(f'{output_dir}/snmp-base.yaml',
                             args.container_id, mibs_enabled, timestamp)

    elif args.output_mode == 'json':
        # Write enriched devices list as JSON for manage_devices.py
        enriched_json_path = f'{output_dir}/enriched-devices.json'
        with open(enriched_json_path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(enriched, f)
        print(f'Written {enriched_json_path} ({len(enriched)} devices)')


if __name__ == '__main__':
    main()
