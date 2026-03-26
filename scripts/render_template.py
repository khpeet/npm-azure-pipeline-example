#!/usr/bin/env python3
"""render_template.py — Simple template file renderer using string replacement.

Runs on pipeline runner.
Substitutes {{CONTAINER_ID}} in docker-compose.template.yml.

Reads a template file, replaces all occurrences of {{KEY}} with the provided
values, and writes the result to the output path.

Usage:
  python3 scripts/render_template.py \\
    --template templates/docker-compose.template.yml \\
    --output /tmp/docker-compose.yml \\
    --set CONTAINER_ID=npm-dc01-01
"""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        description='Render a template file by replacing {{KEY}} placeholders.'
    )
    parser.add_argument('--template', required=True,
                        help='Path to the template file')
    parser.add_argument('--output', required=True,
                        help='Path to write the rendered output')
    parser.add_argument('--set', nargs='+', required=True, metavar='KEY=VALUE',
                        help='One or more KEY=VALUE pairs to substitute (replaces {{KEY}})')
    args = parser.parse_args()

    # Parse key=value pairs
    replacements = {}
    for pair in args.set:
        if '=' not in pair:
            print(f'ERROR: --set value must be KEY=VALUE, got: {pair}')
            sys.exit(1)
        key, value = pair.split('=', 1)
        replacements[key] = value

    # Read template
    with open(args.template, 'r', encoding='utf-8') as f:
        content = f.read()

    # Apply replacements
    for key, value in replacements.items():
        placeholder = '{{' + key + '}}'
        content = content.replace(placeholder, value)

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Write output
    with open(args.output, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)

    print(f'Rendered {args.template} → {args.output}')
    for key, value in replacements.items():
        print(f'  {{{{{key}}}}} = {value}')


if __name__ == '__main__':
    main()
