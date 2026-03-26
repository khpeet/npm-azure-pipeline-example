"""
Shared utilities for device entry building and config YAML generation.

Used by:
  - scripts/generate_config.py         (create action — initial config from device list)
    - scripts/manage_devices.py          (add/update/remove actions — incremental device updates)
  - scripts/merge_probe_results.py     (probe merge — enrichment after device probing)
  - scripts/validate_inputs.py         (input validation for pipeline parameters)

All callers set PYTHONPATH to include scripts/ so this module is importable as:
    from lib.device_utils import build_device_entry, merge_probe_results, write_devices_yaml, ...
"""

import yaml
import os
from datetime import datetime, timezone
from lib.snmp_v3 import build_snmp_v3_entry
from lib.validate_yaml import validate_devices_yaml, validate_snmp_base_yaml


_ENRICHABLE_FIELDS = ['oid', 'mib_profile', 'provider', 'description', 'discovered_mibs']


def merge_probe_results(original_devices, discovered_yaml_content):
    """Merge probe-discovered fields into the original device list.

    For each original device, if the probe discovered data for that device's IP,
    any of the *_ENRICHABLE_FIELDS* that are empty in the original but present in
    the probe output are copied over.  User-supplied values always win.

    Args:
        original_devices: list[dict] — caller-supplied device dicts.
        discovered_yaml_content: str — raw YAML content of discovered-snmp.yaml.

    Returns:
        list[dict] — enriched copies of original_devices (originals are not mutated).
    """
    import yaml

    discovered = {}
    content = discovered_yaml_content.strip() if discovered_yaml_content else ''
    if content and content != '{}':
        try:
            probe_config = yaml.safe_load(content)
            if isinstance(probe_config, dict):
                discovered = probe_config.get('devices', {}) or {}
        except yaml.YAMLError:
            pass

    ip_to_discovered = {}
    for dev_data in discovered.values():
        if isinstance(dev_data, dict):
            ip = dev_data.get('device_ip', '')
            if ip:
                ip_to_discovered[ip] = dev_data

    enriched = []
    for device in original_devices:
        ip = device.get('device_ip', '')
        probe_data = ip_to_discovered.get(ip, {})
        result = dict(device)
        for field in _ENRICHABLE_FIELDS:
            if not device.get(field) and probe_data.get(field):
                result[field] = probe_data[field]
                print(f'  {ip}: {field} filled from probe')
        if probe_data:
            print(f'  {ip}: oid={result.get("oid", "N/A")}, profile={result.get("mib_profile", "N/A")}')
        else:
            print(f'  {ip}: NOT DISCOVERED — keeping original values')
        enriched.append(result)

    return enriched


def build_device_entry(device, snmp_community='public'):
    """Build a device entry dict from a device JSON object.

    Args:
        device: dict with device_name, device_ip, and optional fields
        snmp_community: default SNMP community string fallback

    Returns:
        dict suitable for inclusion in devices.yaml
    """
    name = device.get('device_name', 'unknown')
    ip = device.get('device_ip', '0.0.0.0')
    snmp_v3 = device.get('snmp_v3', None)

    entry = {
        'device_name': name,
        'device_ip': ip,
    }

    if snmp_v3 and isinstance(snmp_v3, dict):
        entry['snmp_v3'] = build_snmp_v3_entry(snmp_v3)
    else:
        entry['snmp_comm'] = device.get('snmp_comm', snmp_community)

    for field in ['mib_profile', 'oid', 'provider', 'description']:
        if device.get(field):
            entry[field] = device[field]

    discovered_mibs = device.get('discovered_mibs', [])
    if discovered_mibs and isinstance(discovered_mibs, list):
        entry['discovered_mibs'] = discovered_mibs

    user_tags = device.get('user_tags', None)
    if user_tags and isinstance(user_tags, dict):
        entry['user_tags'] = user_tags

    ping_only = device.get('ping_only', None)
    if isinstance(ping_only, bool):
        entry['ping_only'] = ping_only

    for field in ['ping_interval_sec', 'poll_time_sec']:
        value = device.get(field, None)
        if value is not None:
            entry[field] = value

    return entry


def compute_mibs_enabled(devices_dict):
    """Compute the union of all MIBs from all devices, always including IF-MIB.

    Args:
        devices_dict: dict of device_name -> device entry

    Returns:
        sorted list of MIB names
    """
    all_mibs = {'IF-MIB'}
    for dev in devices_dict.values():
        if isinstance(dev, dict):
            for mib in dev.get('discovered_mibs', []):
                all_mibs.add(mib)
    return sorted(all_mibs)


def write_devices_yaml(output_path, container_id, devices_dict, timestamp=None):
    """Write devices.yaml from a device map dict.

    Reads the base template header style and writes the populated device map.

    Args:
        output_path: full path to write devices.yaml
        container_id: unique container identifier for header comment
        devices_dict: dict of device_name -> device entry
        timestamp: ISO timestamp string (generated if not provided)
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    header = (
        '# Auto-generated by CI/CD pipeline — do not edit manually.\n'
        '# Mutable device inventory — updated incrementally by add-devices/update-devices/remove-devices actions.\n'
        f'# Container ID: {container_id}\n'
        f'# Generated: {timestamp}\n'
        f'# Devices: {len(devices_dict)}\n'
    )
    with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(header)
        yaml.dump(devices_dict if devices_dict else {}, f,
                  default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Read-back validation: verify the written file is syntactically and structurally valid
    with open(output_path, 'r', encoding='utf-8') as f:
        written_content = f.read()
    is_valid, errors = validate_devices_yaml(written_content, os.path.basename(output_path))
    if not is_valid:
        raise ValueError(
            f'devices.yaml failed read-back validation after write to {output_path}:\n'
            + '\n'.join(f'  - {e}' for e in errors)
        )

    print(f'Written {output_path} ({len(devices_dict)} devices)')


def write_snmp_base_yaml(output_path, container_id, all_mibs, timestamp=None):
    """Write snmp-base.yaml with the @devices.yaml include and computed global block.

    Reads the base template structure and updates mibs_enabled.

    Args:
        output_path: full path to write snmp-base.yaml
        container_id: unique container identifier for header comment
        all_mibs: list of MIB names for mibs_enabled
        timestamp: ISO timestamp string (generated if not provided)
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    global_block = {
        'poll_time_sec': 300,
        'timeout_ms': 5000,
        'retries': 0,
        'mibs_enabled': sorted(all_mibs) if not isinstance(all_mibs, list) else all_mibs,
    }
    global_yaml = yaml.dump(global_block, default_flow_style=False,
                             allow_unicode=True, sort_keys=False)
    indented_global = '\n'.join('  ' + line for line in global_yaml.splitlines())

    with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# Auto-generated by CI/CD pipeline — do not edit manually.\n')
        f.write('# Stable global config. Device inventory is in devices.yaml (referenced via @-include).\n')
        f.write(f'# Container ID: {container_id}\n')
        f.write(f'# Generated: {timestamp}\n')
        f.write('devices:\n')
        f.write('  "@devices.yaml"\n')
        f.write('global:\n')
        f.write(indented_global)
        f.write('\n')

    # Read-back validation: verify the written file is syntactically and structurally valid
    with open(output_path, 'r', encoding='utf-8') as f:
        written_content = f.read()
    is_valid, errors = validate_snmp_base_yaml(written_content, os.path.basename(output_path))
    if not is_valid:
        raise ValueError(
            f'snmp-base.yaml failed read-back validation after write to {output_path}:\n'
            + '\n'.join(f'  - {e}' for e in errors)
        )

    print(f'Written {output_path} (mibs_enabled: {sorted(all_mibs)})')
