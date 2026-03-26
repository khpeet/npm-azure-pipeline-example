#!/usr/bin/env python3
"""generate_probe_config.py — Generate ktranslate discovery YAML for device probing.

Runs on pipeline runner.
Produces a single snmp-probe.yaml file consumed by run-probe.sh on the target host.
No Python or pyyaml is required on the target host — only this runner-side script
needs them.

Usage (CLI):
  python3 scripts/generate_probe_config.py \\
    --devices '<JSON array>' \\
    --snmp-community "public" \\
    --output "/path/to/snmp-probe.yaml"

Usage (Azure Pipeline):
  - task: PythonScript@0
    inputs:
      scriptSource: filePath
      scriptPath: $(Build.SourcesDirectory)/scripts/generate_probe_config.py
      arguments: --output $(Build.ArtifactStagingDirectory)/probe/snmp-probe.yaml
    env:
      DEVICES_JSON: ${{ parameters.devices }}
      SNMP_COMMUNITY: ${{ parameters.snmpCommunity }}
"""

import argparse
import json
import os
import sys

import yaml


def main():
    parser = argparse.ArgumentParser(
        description='Generate ktranslate discovery YAML for device probing.'
    )
    parser.add_argument('--devices', default=None,
                        help='Devices JSON array (or set DEVICES_JSON env var)')
    parser.add_argument('--snmp-community', default=None,
                        help='Default SNMP community string (or set SNMP_COMMUNITY env var)')
    parser.add_argument('--output', required=True,
                        help='Path to write the probe YAML file')
    args = parser.parse_args()

    # Resolve from args or environment variables
    devices_json = args.devices or os.environ.get('DEVICES_JSON', '[]')
    snmp_community = args.snmp_community or os.environ.get('SNMP_COMMUNITY', 'public')

    devices = json.loads(devices_json)

    cidrs = []
    communities = {snmp_community}
    v3_configs = []

    for device in devices:
        ip = device.get('device_ip', '')
        if ip:
            cidrs.append(f'{ip}/32')
        comm = device.get('snmp_comm', '')
        if comm:
            communities.add(comm)
        v3 = device.get('snmp_v3', None)
        if v3 and isinstance(v3, dict):
            v3_configs.append(v3)

    if not cidrs:
        print('ERROR: No device IPs found in devices JSON')
        sys.exit(1)

    config = {
        'discovery': {
            'cidrs': cidrs,
            'default_communities': sorted(communities),
            'default_v3': None,
            'ignore_list': [],
            'ports': [161],
            'add_devices': True,
            'replace_devices': True,
            'add_mibs': True,
            'threads': min(len(cidrs), 2),
            'timeout_ms': 10000,
            'check_all_ips': False,
            'debug': False,
            'use_snmp_v1': False,
        },
        'global': {
            'poll_time_sec': 300,
            'mib_profile_dir': '/etc/ktranslate/profiles',
            'timeout_ms': 5000,
            'retries': 0,
            'mibs_enabled': ['IF-MIB'],
        },
        'devices': {},
    }

    if v3_configs:
        config['discovery']['default_v3'] = v3_configs[0]
        if len(v3_configs) > 1:
            config['discovery']['other_v3s'] = v3_configs[1:]

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, 'w', encoding='utf-8', newline='\n') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f'Probe config generated: {len(cidrs)} CIDR(s), {len(communities)} community string(s)')
    if v3_configs:
        print(f'  SNMPv3 configs: {len(v3_configs)}')


if __name__ == '__main__':
    main()
