#!/usr/bin/env python3
"""validate_config.py — Pipeline-aware wrapper around lib.validate_yaml.

Runs on pipeline runner.

Validates devices.yaml and snmp-base.yaml, sets the YAML_VALIDATION_ERRORS
pipeline variable for downstream use by publish-result-to-nr, and prints
a clear failure banner on error.
"""

import argparse
import os
import sys

# Allow importing lib modules when PYTHONPATH includes scripts/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.validate_yaml import validate_config_files


def main():
    parser = argparse.ArgumentParser(
        description='Validate ktranslate YAML config files with ADO pipeline integration.'
    )
    parser.add_argument('--dir', '-d', required=True,
                        help='Path to directory containing devices.yaml and snmp-base.yaml')
    args = parser.parse_args()

    is_valid, errors = validate_config_files(args.dir)

    if is_valid:
        print('YAML validation passed: devices.yaml and snmp-base.yaml are valid.')
        # Clear the error variable on success
        print('##vso[task.setvariable variable=YAML_VALIDATION_ERRORS]')
        sys.exit(0)
    else:
        print('YAML validation FAILED:', file=sys.stderr)
        for err in errors:
            print(f'  - {err}', file=sys.stderr)

        # Store errors (space-separated) in a pipeline variable for NR reporting
        errors_oneline = ' '.join(err.replace('\n', ' ') for err in errors)
        print(f'##vso[task.setvariable variable=YAML_VALIDATION_ERRORS]{errors_oneline}')

        print()
        print('##############################################################')
        print('YAML VALIDATION FAILED — pipeline halted.')
        print('The current config on the host has NOT been modified.')
        print('No container restart will occur.')
        print('##############################################################')
        sys.exit(1)


if __name__ == '__main__':
    main()
