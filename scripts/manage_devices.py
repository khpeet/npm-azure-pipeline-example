#!/usr/bin/env python3
"""manage_devices.py — Incrementally add, update, or remove devices from devices.yaml.

Runs on pipeline runner.
Operates on devices.yaml fetched from the host (passed as base64 or file path),
then outputs updated devices.yaml and snmp-base.yaml to --output-dir.

Identity and merge rules: based on device_ip.
  - add:    if device_ip already exists → skip + warn (no error).
  - update: device_ip must already exist; supplied fields patch the existing entry.
            device_name may change, but device_ip is immutable.
  - remove: if device_ip not found → warn (no error).

mibs_enabled in snmp-base.yaml is always regenerated as the union of all
remaining devices' discovered_mibs after any add, update, or remove operation.
"""

import argparse
import base64
import copy
import json
import os
import sys
from datetime import datetime, timezone

import yaml

# Allow importing lib.device_utils when PYTHONPATH includes scripts/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.device_utils import (
    build_device_entry,
    compute_mibs_enabled,
    write_devices_yaml,
    write_snmp_base_yaml,
)


def load_existing_devices(existing_b64):
    """Decode and load an existing devices.yaml payload from base64."""
    try:
        existing_yaml = base64.b64decode(existing_b64).decode('utf-8')
    except Exception as exc:
        raise ValueError(f'Failed to decode existing devices base64: {exc}') from exc

    existing_devices = yaml.safe_load(existing_yaml) or {}
    if not isinstance(existing_devices, dict):
        raise ValueError('existing devices.yaml is not a device map')

    return existing_devices


def build_ip_to_key_map(devices_dict):
    """Return the current device_ip → YAML key lookup."""
    ip_to_key = {}
    for key, dev in devices_dict.items():
        if isinstance(dev, dict):
            ip = dev.get('device_ip', '')
            if ip:
                ip_to_key[ip] = key
    return ip_to_key


def add_devices(existing_devices, new_devices, snmp_community):
    """Append new devices, skipping duplicate device_ip values."""
    updated_devices = copy.deepcopy(existing_devices)
    ip_to_key = build_ip_to_key_map(updated_devices)
    added = 0
    skipped = 0

    for idx, device in enumerate(new_devices):
        ip = device.get('device_ip', '')
        name = device.get('device_name', '')
        if not ip or not name:
            print(f'WARNING: Device at index {idx} is missing device_ip or device_name — skipping')
            skipped += 1
            continue

        if ip in ip_to_key:
            existing_key = ip_to_key[ip]
            print(f'WARNING: device_ip {ip} already exists (key: {existing_key}) — skipping (use remove-devices first to replace)')
            skipped += 1
            continue

        entry = build_device_entry(device, snmp_community)
        updated_devices[name] = entry
        ip_to_key[ip] = name
        added += 1
        print(f'  Added: {name} ({ip})')

    return updated_devices, added, skipped


def update_devices(existing_devices, device_patches, snmp_community):
    """Patch existing devices matched by immutable device_ip."""
    updated_devices = copy.deepcopy(existing_devices)
    ip_to_key = build_ip_to_key_map(updated_devices)
    plans = {}

    for idx, patch in enumerate(device_patches):
        ip = patch.get('device_ip', '')
        if not ip:
            raise ValueError(f'Update entry at index {idx} is missing device_ip')

        current_key = ip_to_key.get(ip)
        if not current_key:
            raise ValueError(
                f'device_ip {ip} was not found in devices.yaml; use add-devices to add it first'
            )

        current_entry = updated_devices.get(current_key)
        if not isinstance(current_entry, dict):
            raise ValueError(f'device entry for {current_key} is not a valid mapping')

        current_ip = current_entry.get('device_ip')
        if current_ip != ip:
            raise ValueError(
                f'device_ip mismatch for {current_key}: expected {current_ip}, got {ip}; device_ip is immutable'
            )

        target_name = patch.get('device_name', current_entry.get('device_name') or current_key)
        if not target_name:
            raise ValueError(f'device_ip {ip} cannot be updated to an empty device_name')

        merged_source = copy.deepcopy(current_entry)
        for field, value in patch.items():
            if field == 'device_ip':
                continue
            merged_source[field] = copy.deepcopy(value)

        if 'snmp_v3' in patch:
            merged_source.pop('snmp_comm', None)
        if 'snmp_comm' in patch:
            merged_source.pop('snmp_v3', None)

        merged_source['device_name'] = target_name
        merged_source['device_ip'] = current_ip
        plans[current_key] = {
            'entry': build_device_entry(merged_source, snmp_community),
            'ip': ip,
            'target_name': target_name,
        }

    final_keys = []
    for current_key in updated_devices:
        if current_key in plans:
            final_keys.append(plans[current_key]['target_name'])
        else:
            final_keys.append(current_key)

    if len(final_keys) != len(set(final_keys)):
        duplicate_names = sorted({name for name in final_keys if final_keys.count(name) > 1})
        raise ValueError(
            'device_name collision detected for update-devices: '
            + ', '.join(duplicate_names)
        )

    final_devices = {}
    updated_count = 0
    renamed_count = 0
    for current_key, entry in updated_devices.items():
        if current_key not in plans:
            final_devices[current_key] = entry
            continue

        plan = plans[current_key]
        target_name = plan['target_name']
        final_devices[target_name] = plan['entry']
        updated_count += 1
        if target_name != current_key:
            renamed_count += 1
            print(f'  Updated + renamed: {current_key} -> {target_name} ({plan["ip"]})')
        else:
            print(f'  Updated: {target_name} ({plan["ip"]})')

    return final_devices, updated_count, renamed_count


def remove_devices_by_ip(existing_devices, remove_devices):
    """Remove devices whose device_ip matches the removal payload."""
    updated_devices = copy.deepcopy(existing_devices)
    ip_to_key = build_ip_to_key_map(updated_devices)
    removed = 0
    not_found = 0

    for idx, device in enumerate(remove_devices):
        ip = device.get('device_ip', '')
        if not ip:
            print(f'WARNING: Remove entry at index {idx} is missing device_ip — skipping')
            not_found += 1
            continue

        if ip not in ip_to_key:
            print(f'WARNING: device_ip {ip} not found in devices.yaml — skipping')
            not_found += 1
            continue

        key = ip_to_key[ip]
        del updated_devices[key]
        del ip_to_key[ip]
        removed += 1
        print(f'  Removed: {key} ({ip})')

    return updated_devices, removed, not_found


def save_devices_files(output_dir, container_id, devices_dict, timestamp):
    """Write updated devices.yaml and snmp-base.yaml files."""
    write_devices_yaml(f'{output_dir}/devices.yaml', container_id, devices_dict, timestamp)
    mibs_enabled = compute_mibs_enabled(devices_dict)
    write_snmp_base_yaml(f'{output_dir}/snmp-base.yaml', container_id, mibs_enabled, timestamp)


def main():
    parser = argparse.ArgumentParser(
        description='Incrementally add, update, or remove devices from devices.yaml.'
    )
    parser.add_argument('--action', required=True, choices=['add', 'update', 'remove'],
                        help='Action: add, update, or remove devices')
    parser.add_argument('--container-id', required=True,
                        help='Unique container identifier')
    parser.add_argument('--existing-devices-b64', default=None,
                        help='Base64-encoded existing devices.yaml (or set EXISTING_DEVICES_B64 env var)')
    parser.add_argument('--new-devices', default=None,
                        help='JSON array of devices to add or update (or set NEW_DEVICES_JSON env var)')
    parser.add_argument('--remove-devices', default=None,
                        help='JSON array of devices to remove (or set REMOVE_DEVICES_JSON env var)')
    parser.add_argument('--snmp-community', default=None,
                        help='Default SNMP community string (or set SNMP_COMMUNITY env var)')
    parser.add_argument('--output-dir', required=True,
                        help='Directory to write updated config files into')
    args = parser.parse_args()

    existing_b64 = args.existing_devices_b64 or os.environ.get('EXISTING_DEVICES_B64', '')
    new_devices_json = args.new_devices or os.environ.get('NEW_DEVICES_JSON', '[]')
    rm_devices_json = args.remove_devices or os.environ.get('REMOVE_DEVICES_JSON', '[]')
    snmp_community = args.snmp_community or os.environ.get('SNMP_COMMUNITY', 'public')
    output_dir = args.output_dir.rstrip('/')
    container_id = args.container_id

    if not existing_b64:
        print('ERROR: --existing-devices-b64 (or EXISTING_DEVICES_B64 env var) is required')
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    try:
        existing_devices = load_existing_devices(existing_b64)
    except ValueError as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)

    if args.action == 'add':
        try:
            new_devices = json.loads(new_devices_json)
        except json.JSONDecodeError as exc:
            print(f'ERROR: Invalid new-devices JSON: {exc}')
            sys.exit(1)

        existing_devices, added, skipped = add_devices(existing_devices, new_devices, snmp_community)
        print(f'Add result: {added} added, {skipped} skipped (duplicate IP or missing fields)')

    elif args.action == 'update':
        try:
            device_patches = json.loads(new_devices_json)
        except json.JSONDecodeError as exc:
            print(f'ERROR: Invalid new-devices JSON: {exc}')
            sys.exit(1)

        try:
            existing_devices, updated, renamed = update_devices(
                existing_devices,
                device_patches,
                snmp_community,
            )
        except ValueError as exc:
            print(f'ERROR: {exc}')
            sys.exit(1)

        print(f'Update result: {updated} updated, {renamed} renamed')

    elif args.action == 'remove':
        try:
            remove_devices = json.loads(rm_devices_json)
        except json.JSONDecodeError as exc:
            print(f'ERROR: Invalid remove-devices JSON: {exc}')
            sys.exit(1)

        existing_devices, removed, not_found = remove_devices_by_ip(existing_devices, remove_devices)
        print(f'Remove result: {removed} removed, {not_found} not found (warnings only)')

    save_devices_files(output_dir, container_id, existing_devices, timestamp)
    print('manage_devices.py complete.')


if __name__ == '__main__':
    main()
