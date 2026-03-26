#!/usr/bin/env python3
"""validate_fetched_devices.py — Validate base64-encoded devices.yaml from host.

Runs on pipeline runner.
Decodes the base64 input, validates the YAML structure, and sets Azure DevOps
pipeline variables for error reporting.
"""

import base64
import os
import sys

# Allow importing lib modules when PYTHONPATH includes scripts/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.validate_yaml import validate_devices_yaml


def main():
    devices_b64 = os.environ.get('DEVICES_B64_VALUE', '')

    if not devices_b64:
        print('ERROR: DEVICES_B64_VALUE environment variable is empty or not set')
        print('##vso[task.setvariable variable=YAML_VALIDATION_ERRORS]DEVICES_B64_VALUE is empty')
        _print_failure_banner()
        sys.exit(1)

    # Decode base64
    try:
        content = base64.b64decode(devices_b64).decode('utf-8')
    except Exception as e:
        msg = f'Failed to decode base64 devices: {e}'
        print(f'ERROR: {msg}')
        print(f'##vso[task.setvariable variable=YAML_VALIDATION_ERRORS]{msg}')
        _print_failure_banner()
        sys.exit(1)

    print('Validating fetched devices.yaml from host...')

    is_valid, errors = validate_devices_yaml(content, 'devices.yaml (fetched from host)')

    if is_valid:
        print('Fetched devices.yaml is valid.')
        # Clear the error variable on success
        print('##vso[task.setvariable variable=YAML_VALIDATION_ERRORS]')
        sys.exit(0)
    else:
        print('Fetched devices.yaml is INVALID:')
        for e in errors:
            print(f'  - {e}')

        errors_oneline = ' '.join(e.replace('\n', ' ') for e in errors)
        print(f'##vso[task.setvariable variable=YAML_VALIDATION_ERRORS]{errors_oneline}')
        _print_failure_banner()
        sys.exit(1)


def _print_failure_banner():
    """Print the failure banner matching the original pipeline step."""
    print()
    print('##############################################################')
    print('FETCHED devices.yaml VALIDATION FAILED — pipeline halted.')
    print('The devices.yaml on the host appears corrupted.')
    print('Manual inspection and repair of the host config is required.')
    print('No changes will be made. The container continues running as-is.')
    print('##############################################################')


if __name__ == '__main__':
    main()
