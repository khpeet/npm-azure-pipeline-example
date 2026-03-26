#!/usr/bin/env python3
"""generate_config.py — Generate snmp-base.yaml and devices.yaml from parameters.

Runs on pipeline runner.
Replaces the former generate-config.sh bash wrapper.

Outputs two files:
  snmp-base.yaml  — Stable global config referencing devices.yaml via @-include.
                    Only changes when global settings or mibs_enabled changes.
  devices.yaml    — Mutable device inventory (flat device map).
                    Accumulated and updated incrementally across pipeline runs.

Usage (CLI):
  python3 scripts/generate_config.py \\
    --container-id "npm-tokyo-01" \\
    --devices '<JSON array>' \\
    --snmp-community "public" \\
    --output-dir "/path/to/output/"
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Allow importing lib.device_utils when PYTHONPATH includes scripts/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.device_utils import (
    build_device_entry,
    compute_mibs_enabled,
    write_devices_yaml,
    write_snmp_base_yaml,
)


def main():
    parser = argparse.ArgumentParser(
        description='Generate snmp-base.yaml and devices.yaml from device JSON.'
    )
    parser.add_argument('--container-id', required=True,
                        help='Unique container identifier (e.g., npm-dc01-01)')
    parser.add_argument('--devices', default=None,
                        help='Devices JSON array (or set DEVICES_JSON env var)')
    parser.add_argument('--snmp-community', default=None,
                        help='Default SNMP community string (or set SNMP_COMMUNITY env var)')
    parser.add_argument('--output-dir', required=True,
                        help='Directory to write config files into')
    args = parser.parse_args()

    # Resolve from args or environment variables
    devices_json = args.devices or os.environ.get('DEVICES_JSON', '[]')
    snmp_community = args.snmp_community or os.environ.get('SNMP_COMMUNITY', 'public')
    output_dir = args.output_dir.rstrip('/')

    try:
        devices = json.loads(devices_json)
    except json.JSONDecodeError as e:
        print(f'ERROR: Invalid devices JSON: {e}')
        sys.exit(1)

    if not isinstance(devices, list):
        print('ERROR: devices must be a JSON array')
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    print(f'Generating config files for container: {args.container_id}')

    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Build devices map
    devices_dict = {}
    for device in devices:
        name = device.get('device_name', 'unknown')
        entry = build_device_entry(device, snmp_community)
        devices_dict[name] = entry

    # Write config files
    write_devices_yaml(f'{output_dir}/devices.yaml',
                       args.container_id, devices_dict, timestamp)

    mibs_enabled = compute_mibs_enabled(devices_dict)
    write_snmp_base_yaml(f'{output_dir}/snmp-base.yaml',
                         args.container_id, mibs_enabled, timestamp)

    print('Config generation complete.')


if __name__ == '__main__':
    main()
