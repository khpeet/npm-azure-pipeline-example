"""
Structural YAML validation for ktranslate config files.

Used by:
  - scripts/lib/device_utils.py (read-back validation after each write)
  - pipelines/templates/steps/validate-config.yml (pipeline validation gate)

Validates devices.yaml and snmp-base.yaml for:
  - Syntactic correctness (parseable YAML)
  - Structural correctness (required keys, correct types, expected values)

CLI usage:
  python3 -m lib.validate_yaml --dir <path-to-config-dir>
  Exits 0 on success, 1 on failure. Errors are printed to stderr.
"""

import re
import sys
import yaml
import os
import argparse
from typing import Tuple

from lib.snmp_v3 import validate_snmp_v3_object

# IPv4 address pattern (basic — same requirement as the pipeline validation stage)
_IPV4_RE = re.compile(
    r'^((25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d|\d)\.){3}'
    r'(25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d|\d)$'
)


def validate_ipv4(ip: str) -> bool:
    """Check whether *ip* is a valid dotted-decimal IPv4 address.

    Uses the same compiled regex as the per-device validators so behaviour is
    identical everywhere in the pipeline.

    Args:
        ip: string to test.

    Returns:
        True when *ip* is a valid IPv4 address, False otherwise.
    """
    return bool(_IPV4_RE.match(ip))


def _safe_yaml_error(e: yaml.YAMLError) -> str:
    """Return a sanitized error description that omits surrounding file content.

    PyYAML's str(YAMLError) includes the file lines around the error which may
    contain SNMP community strings or other credentials.  This helper extracts
    only the problem description and its line/column position.
    """
    parts = []
    if hasattr(e, 'context') and e.context:
        parts.append(str(e.context))
        if hasattr(e, 'context_mark') and e.context_mark:
            parts.append(f'(line {e.context_mark.line + 1})')
    if hasattr(e, 'problem') and e.problem:
        parts.append(str(e.problem))
    if hasattr(e, 'problem_mark') and e.problem_mark:
        parts.append(f'at line {e.problem_mark.line + 1}, column {e.problem_mark.column + 1}')
    return ', '.join(parts) if parts else 'unknown parse error'


# ── devices.yaml validation ──────────────────────────────────────────────────

def validate_devices_yaml(content: str, filename: str = 'devices.yaml') -> Tuple[bool, list]:
    """Validate devices.yaml content.

    Args:
        content: raw YAML string
        filename: label used in error messages

    Returns:
        (is_valid, errors) — errors is a list of human-readable strings
    """
    errors = []

    # 1. Parse
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return False, [f'{filename}: YAML syntax error: {_safe_yaml_error(e)}']

    # 2. Root must be a dict (or None/empty — empty device list is allowed)
    if data is None:
        data = {}

    if not isinstance(data, dict):
        return False, [f'{filename}: root must be a mapping (dict), got {type(data).__name__}']

    # 3. Validate each device entry
    for key, entry in data.items():
        prefix = f'{filename}: device "{key}"'

        if not isinstance(entry, dict):
            errors.append(f'{prefix}: entry must be a mapping, got {type(entry).__name__}')
            continue

        # Required: device_name
        device_name = entry.get('device_name')
        if not device_name:
            errors.append(f'{prefix}: missing required field "device_name"')
        elif not isinstance(device_name, str):
            errors.append(f'{prefix}: "device_name" must be a string, got {type(device_name).__name__}')

        # Required: device_ip (valid IPv4)
        device_ip = entry.get('device_ip')
        if not device_ip:
            errors.append(f'{prefix}: missing required field "device_ip"')
        elif not isinstance(device_ip, str):
            errors.append(f'{prefix}: "device_ip" must be a string, got {type(device_ip).__name__}')
        elif not _IPV4_RE.match(device_ip):
            errors.append(f'{prefix}: "device_ip" is not a valid IPv4 address: {device_ip!r}')

        # Optional: snmp_comm must be a string if present
        snmp_comm = entry.get('snmp_comm')
        if snmp_comm is not None and not isinstance(snmp_comm, str):
            errors.append(f'{prefix}: "snmp_comm" must be a string, got {type(snmp_comm).__name__}')

        # Optional: snmp_v3 must be a dict with required sub-keys if present
        snmp_v3 = entry.get('snmp_v3')
        if snmp_v3 is not None:
            yaml_prefix = f'{prefix}:'
            for message in validate_snmp_v3_object(snmp_v3, yaml_prefix):
                errors.append(message.replace(' field ', ' ', 1))

        # Optional: discovered_mibs must be a list of strings if present
        discovered_mibs = entry.get('discovered_mibs')
        if discovered_mibs is not None:
            if not isinstance(discovered_mibs, list):
                errors.append(f'{prefix}: "discovered_mibs" must be a list, got {type(discovered_mibs).__name__}')
            else:
                for i, mib in enumerate(discovered_mibs):
                    if not isinstance(mib, str):
                        errors.append(f'{prefix}: "discovered_mibs[{i}]" must be a string, got {type(mib).__name__}')

        # Optional: user_tags must be a dict if present
        user_tags = entry.get('user_tags')
        if user_tags is not None and not isinstance(user_tags, dict):
            errors.append(f'{prefix}: "user_tags" must be a mapping, got {type(user_tags).__name__}')

        # Optional: ping_only must be a boolean if present
        ping_only = entry.get('ping_only')
        if ping_only is not None and not isinstance(ping_only, bool):
            errors.append(f'{prefix}: "ping_only" must be a boolean, got {type(ping_only).__name__}')

        # Optional: per-device poll overrides must be positive integers if present
        for field in ('ping_interval_sec', 'poll_time_sec'):
            value = entry.get(field)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f'{prefix}: "{field}" must be an integer, got {type(value).__name__}')
            elif value <= 0:
                errors.append(f'{prefix}: "{field}" must be > 0, got {value}')

        # Optional string fields
        for field in ('mib_profile', 'oid', 'provider', 'description'):
            val = entry.get(field)
            if val is not None and not isinstance(val, str):
                errors.append(f'{prefix}: "{field}" must be a string, got {type(val).__name__}')

    return len(errors) == 0, errors


# ── snmp-base.yaml validation ────────────────────────────────────────────────

def validate_snmp_base_yaml(content: str, filename: str = 'snmp-base.yaml') -> Tuple[bool, list]:
    """Validate snmp-base.yaml content.

    Args:
        content: raw YAML string
        filename: label used in error messages

    Returns:
        (is_valid, errors) — errors is a list of human-readable strings
    """
    errors = []

    # 1. Parse
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return False, [f'{filename}: YAML syntax error: {_safe_yaml_error(e)}']

    # 2. Root must be a non-empty dict
    if data is None or not isinstance(data, dict):
        return False, [f'{filename}: root must be a non-empty mapping, got {type(data).__name__ if data is not None else "null"}']

    # 3. Required: devices key containing the @-include reference
    devices_val = data.get('devices')
    if devices_val is None:
        errors.append(f'{filename}: missing required key "devices"')
    elif not isinstance(devices_val, str) or '@devices.yaml' not in devices_val:
        errors.append(
            f'{filename}: "devices" must be the @-include string "@devices.yaml", '
            f'got {devices_val!r}'
        )

    # 4. Required: global block
    global_block = data.get('global')
    if global_block is None:
        errors.append(f'{filename}: missing required key "global"')
    elif not isinstance(global_block, dict):
        errors.append(f'{filename}: "global" must be a mapping, got {type(global_block).__name__}')
    else:
        # poll_time_sec — required int
        poll_time = global_block.get('poll_time_sec')
        if poll_time is None:
            errors.append(f'{filename}: "global.poll_time_sec" is required')
        elif not isinstance(poll_time, int) or isinstance(poll_time, bool):
            errors.append(f'{filename}: "global.poll_time_sec" must be an integer, got {type(poll_time).__name__}')
        elif poll_time <= 0:
            errors.append(f'{filename}: "global.poll_time_sec" must be > 0, got {poll_time}')

        # timeout_ms — required int
        timeout_ms = global_block.get('timeout_ms')
        if timeout_ms is None:
            errors.append(f'{filename}: "global.timeout_ms" is required')
        elif not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
            errors.append(f'{filename}: "global.timeout_ms" must be an integer, got {type(timeout_ms).__name__}')
        elif timeout_ms <= 0:
            errors.append(f'{filename}: "global.timeout_ms" must be > 0, got {timeout_ms}')

        # retries — required int (0 is valid)
        retries = global_block.get('retries')
        if retries is None:
            errors.append(f'{filename}: "global.retries" is required')
        elif not isinstance(retries, int) or isinstance(retries, bool):
            errors.append(f'{filename}: "global.retries" must be an integer, got {type(retries).__name__}')
        elif retries < 0:
            errors.append(f'{filename}: "global.retries" must be >= 0, got {retries}')

        # mibs_enabled — required non-empty list of strings
        mibs_enabled = global_block.get('mibs_enabled')
        if mibs_enabled is None:
            errors.append(f'{filename}: "global.mibs_enabled" is required')
        elif not isinstance(mibs_enabled, list):
            errors.append(f'{filename}: "global.mibs_enabled" must be a list, got {type(mibs_enabled).__name__}')
        elif len(mibs_enabled) == 0:
            errors.append(f'{filename}: "global.mibs_enabled" must not be empty (at minimum IF-MIB is expected)')
        else:
            for i, mib in enumerate(mibs_enabled):
                if not isinstance(mib, str):
                    errors.append(f'{filename}: "global.mibs_enabled[{i}]" must be a string, got {type(mib).__name__}')

    return len(errors) == 0, errors


# ── Combined config directory validation ─────────────────────────────────────

def validate_config_files(config_dir: str) -> Tuple[bool, list]:
    """Validate both devices.yaml and snmp-base.yaml in a config directory.

    Args:
        config_dir: path to directory containing devices.yaml and snmp-base.yaml

    Returns:
        (is_valid, errors) — errors is a combined list from both files
    """
    all_errors = []
    overall_valid = True

    for filename, validate_fn in [
        ('devices.yaml', validate_devices_yaml),
        ('snmp-base.yaml', validate_snmp_base_yaml),
    ]:
        filepath = os.path.join(config_dir, filename)

        if not os.path.exists(filepath):
            all_errors.append(f'{filename}: file not found at {filepath}')
            overall_valid = False
            continue

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError as e:
            all_errors.append(f'{filename}: cannot read file: {e}')
            overall_valid = False
            continue

        valid, errors = validate_fn(content)
        if not valid:
            all_errors.extend(errors)
            overall_valid = False

    return overall_valid, all_errors


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Validate ktranslate YAML config files (devices.yaml, snmp-base.yaml).'
    )
    parser.add_argument(
        '--dir', '-d',
        required=True,
        help='Path to directory containing devices.yaml and snmp-base.yaml',
    )
    args = parser.parse_args()

    is_valid, errors = validate_config_files(args.dir)

    if is_valid:
        print('YAML validation passed: devices.yaml and snmp-base.yaml are valid.')
        sys.exit(0)
    else:
        print('YAML validation FAILED:', file=sys.stderr)
        for err in errors:
            print(f'  - {err}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
