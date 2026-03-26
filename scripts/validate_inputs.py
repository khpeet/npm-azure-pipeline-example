#!/usr/bin/env python3
"""validate_inputs.py — Validate pipeline input parameters for device JSON arrays.

Runs on pipeline runner.

Validates:
    - devices JSON array (for create / add-devices / update-devices actions)
    - removeDevices JSON array (for remove-devices action)

Create/add devices must have device_name (str) and device_ip (valid IPv4).
Update devices are matched by immutable device_ip and may be partial patches.
"""

import argparse
import json
import os
import sys

# Allow importing lib modules when PYTHONPATH includes scripts/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.snmp_v3 import validate_snmp_v3_object
from lib.validate_yaml import validate_ipv4


UPDATE_ALLOWED_FIELDS = {
    'description',
    'device_ip',
    'device_name',
    'discovered_mibs',
    'mib_profile',
    'oid',
    'ping_interval_sec',
    'ping_only',
    'poll_time_sec',
    'provider',
    'snmp_comm',
    'snmp_v3',
    'user_tags',
}

OPTIONAL_STRING_FIELDS = ('mib_profile', 'oid', 'provider', 'description')
OPTIONAL_INT_FIELDS = ('ping_interval_sec', 'poll_time_sec')


def validate_device_array(json_str, label, action):
    """Validate a JSON array of devices.

    Args:
        json_str: raw JSON string.
        label: human-readable name for error messages (e.g. "devices", "removeDevices").

    Returns:
        (is_valid, error_messages) tuple.
    """
    errors = []
    try:
        devices = json.loads(json_str)
    except json.JSONDecodeError as e:
        return False, [f'ERROR: {label} is not valid JSON: {e}']

    if not isinstance(devices, list):
        return False, [f'ERROR: {label} must be a JSON array']

    if len(devices) == 0:
        return False, [f'ERROR: {label} array is empty. At least one device is required.']

    seen_update_ips = set()

    for idx, d in enumerate(devices):
        if not isinstance(d, dict):
            errors.append(
                f'ERROR: {label} entry at index {idx} must be a JSON object, got {type(d).__name__}'
            )
            continue

        if action == 'update-devices':
            unknown_fields = sorted(set(d) - UPDATE_ALLOWED_FIELDS)
            if unknown_fields:
                errors.append(
                    f'ERROR: {label} entry at index {idx} contains unsupported fields: '
                    + ', '.join(unknown_fields)
                )
                for field in unknown_fields:
                    if 'device_ip' in field and field != 'device_ip':
                        errors.append(
                            f'ERROR: {label} entry at index {idx} attempts to change immutable device_ip via field {field}; '
                            'use add-devices + remove-devices for IP changes'
                        )

        ip = d.get('device_ip', '')
        if not ip:
            errors.append(f'ERROR: {label} entry at index {idx} is missing required field device_ip')
            continue
        if not validate_ipv4(ip):
            errors.append(f'ERROR: device_ip is not a valid IPv4 address: {ip}')

        if action == 'update-devices':
            if ip in seen_update_ips:
                errors.append(
                    f'ERROR: {label} contains duplicate update target device_ip: {ip}'
                )
            else:
                seen_update_ips.add(ip)

        # device_name is required for create/add devices.
        if label == 'devices' and action in ('create', 'add-devices') and not d.get('device_name'):
            errors.append(
                f'ERROR: device at index {idx} (ip: {ip}) is missing required field device_name'
            )

        if label != 'devices':
            continue

        prefix = f'device at index {idx} (ip: {ip})'

        if action == 'update-devices' and len(set(d.keys()) - {'device_ip'}) == 0:
            errors.append(
                f'ERROR: {prefix} must include at least one updatable field in addition to device_ip'
            )

        if 'device_name' in d:
            device_name = d.get('device_name')
            if not isinstance(device_name, str) or not device_name:
                errors.append(f'ERROR: {prefix} field device_name must be a non-empty string')

        if 'snmp_comm' in d:
            snmp_comm = d.get('snmp_comm')
            if not isinstance(snmp_comm, str) or not snmp_comm:
                errors.append(f'ERROR: {prefix} field snmp_comm must be a non-empty string')

        if 'snmp_comm' in d and 'snmp_v3' in d:
            errors.append(
                f'ERROR: {prefix} cannot include both snmp_comm and snmp_v3 in the same payload'
            )

        if 'snmp_v3' in d:
            errors.extend(
                f'ERROR: {message}'
                for message in validate_snmp_v3_object(d.get('snmp_v3'), prefix)
            )

        user_tags = d.get('user_tags')
        if user_tags is not None and not isinstance(user_tags, dict):
            errors.append(
                f'ERROR: {prefix} field user_tags must be an object'
            )

        ping_only = d.get('ping_only')
        if ping_only is not None and not isinstance(ping_only, bool):
            errors.append(
                f'ERROR: {prefix} field ping_only must be a boolean'
            )

        discovered_mibs = d.get('discovered_mibs')
        if discovered_mibs is not None:
            if not isinstance(discovered_mibs, list):
                errors.append(f'ERROR: {prefix} field discovered_mibs must be an array')
            else:
                for mib_idx, mib in enumerate(discovered_mibs):
                    if not isinstance(mib, str):
                        errors.append(
                            f'ERROR: {prefix} field discovered_mibs[{mib_idx}] must be a string'
                        )

        for field in OPTIONAL_STRING_FIELDS:
            value = d.get(field)
            if value is not None and not isinstance(value, str):
                errors.append(f'ERROR: {prefix} field {field} must be a string')

        for field in OPTIONAL_INT_FIELDS:
            value = d.get(field)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(
                    f'ERROR: {prefix} field {field} must be an integer'
                )
            elif value <= 0:
                errors.append(
                    f'ERROR: {prefix} field {field} must be > 0'
                )

    if errors:
        return False, errors

    return True, [f'{label} validated: {len(devices)} device(s)']


def main():
    parser = argparse.ArgumentParser(
        description='Validate pipeline input parameters (devices/removeDevices JSON arrays).'
    )
    parser.add_argument('--action', required=True,
                        help='Pipeline action (create, add-devices, update-devices, remove-devices, start, stop, remove)')
    args = parser.parse_args()

    error_count = 0

    if args.action == 'update-devices' and os.environ.get('PROBE_DEVICES', 'false').lower() == 'true':
        print('ERROR: probeDevices=true is not supported for update-devices. Use create/add-devices for probe enrichment.')
        error_count += 1

    # Validate devices for create / add-devices
    if args.action in ('create', 'add-devices', 'update-devices'):
        devices_json = os.environ.get('DEVICES_JSON', '[]')
        is_valid, messages = validate_device_array(devices_json, 'devices', args.action)
        for msg in messages:
            print(msg)
        if not is_valid:
            error_count += 1

    # Validate removeDevices for remove-devices
    if args.action == 'remove-devices':
        rm_json = os.environ.get('REMOVE_DEVICES_JSON', '[]')
        is_valid, messages = validate_device_array(rm_json, 'removeDevices', args.action)
        for msg in messages:
            print(msg)
        if not is_valid:
            error_count += 1

    if error_count > 0:
        print(f'\nDevice input validation failed with {error_count} error(s).')
        sys.exit(1)

    print('Device input validation passed.')


if __name__ == '__main__':
    main()
