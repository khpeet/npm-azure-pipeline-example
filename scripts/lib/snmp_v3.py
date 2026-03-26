"""Shared SNMPv3 schema helpers.

Used by:
  - scripts/validate_inputs.py
  - scripts/lib/validate_yaml.py
  - scripts/lib/device_utils.py
"""

SNMP_V3_REQUIRED_FIELDS = (
    'user_name',
    'authentication_protocol',
    'privacy_protocol',
)

SNMP_V3_ALLOWED_FIELDS = (
    'user_name',
    'authentication_protocol',
    'authentication_passphrase',
    'privacy_protocol',
    'privacy_passphrase',
    'context_engine_id',
    'context_name',
)

SNMP_V3_AUTH_PROTOCOLS = (
    'NoAuth',
    'MD5',
    'SHA',
)

SNMP_V3_PRIVACY_PROTOCOLS = (
    'NoPriv',
    'DES',
    'AES',
    'AES192',
    'AES256',
    'AES192C',
    'AES256C',
)


def validate_snmp_v3_object(snmp_v3, prefix):
    """Return validation errors for an SNMPv3 object.

    Args:
        snmp_v3: candidate SNMPv3 value.
        prefix: leading message prefix, without any ERROR decoration.

    Returns:
        list[str]: validation errors.
    """
    errors = []

    if not isinstance(snmp_v3, dict):
        return [f'{prefix} field snmp_v3 must be an object']

    unknown_fields = sorted(set(snmp_v3) - set(SNMP_V3_ALLOWED_FIELDS))
    if unknown_fields:
        errors.append(
            f'{prefix} field snmp_v3 contains unsupported keys: {", ".join(unknown_fields)}'
        )

    user_name = snmp_v3.get('user_name')
    if not isinstance(user_name, str) or not user_name:
        errors.append(f'{prefix} field snmp_v3.user_name must be a non-empty string')

    auth_protocol = snmp_v3.get('authentication_protocol')
    if not isinstance(auth_protocol, str) or not auth_protocol:
        errors.append(
            f'{prefix} field snmp_v3.authentication_protocol must be a non-empty string'
        )
    elif auth_protocol not in SNMP_V3_AUTH_PROTOCOLS:
        errors.append(
            f'{prefix} field snmp_v3.authentication_protocol must be one of: '
            + ', '.join(SNMP_V3_AUTH_PROTOCOLS)
        )

    privacy_protocol = snmp_v3.get('privacy_protocol')
    if not isinstance(privacy_protocol, str) or not privacy_protocol:
        errors.append(
            f'{prefix} field snmp_v3.privacy_protocol must be a non-empty string'
        )
    elif privacy_protocol not in SNMP_V3_PRIVACY_PROTOCOLS:
        errors.append(
            f'{prefix} field snmp_v3.privacy_protocol must be one of: '
            + ', '.join(SNMP_V3_PRIVACY_PROTOCOLS)
        )

    auth_passphrase = snmp_v3.get('authentication_passphrase')
    if auth_passphrase is not None and not isinstance(auth_passphrase, str):
        errors.append(
            f'{prefix} field snmp_v3.authentication_passphrase must be a string'
        )
    if isinstance(auth_protocol, str) and auth_protocol != 'NoAuth' and not auth_passphrase:
        errors.append(
            f'{prefix} field snmp_v3.authentication_passphrase is required when authentication_protocol is not NoAuth'
        )

    privacy_passphrase = snmp_v3.get('privacy_passphrase')
    if privacy_passphrase is not None and not isinstance(privacy_passphrase, str):
        errors.append(
            f'{prefix} field snmp_v3.privacy_passphrase must be a string'
        )
    if isinstance(privacy_protocol, str) and privacy_protocol != 'NoPriv' and not privacy_passphrase:
        errors.append(
            f'{prefix} field snmp_v3.privacy_passphrase is required when privacy_protocol is not NoPriv'
        )

    for field in ('context_engine_id', 'context_name'):
        value = snmp_v3.get(field)
        if value is not None and not isinstance(value, str):
            errors.append(f'{prefix} field snmp_v3.{field} must be a string')

    return errors


def build_snmp_v3_entry(snmp_v3):
    """Return an ordered SNMPv3 mapping containing supported fields only."""
    entry = {}
    for field in SNMP_V3_ALLOWED_FIELDS:
        value = snmp_v3.get(field)
        if value is None:
            continue
        if field in SNMP_V3_REQUIRED_FIELDS or value != '':
            entry[field] = value
    return entry
