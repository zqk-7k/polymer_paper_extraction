"""Default-on switchboard for the declared parse levers.

The three declared parse levers (T1 external-parser candidates, T2 declared
spelling repairs, T3 declared naming variants) are **on by default** under the
maintainer decision recorded in ``docs/ADR-005`` and ``docs/ADR-006``.  They can
still be switched off explicitly, and with every lever off the registry is back
on the legacy namespace byte for byte::

    POLYMER_PARSE_LEVERS=0|off|false|no     -> legacy namespace: no T3, no T2
    POLYMER_PARSE_LEVERS=1|on               -> explicit on (this is the default)
    POLYMER_EXTERNAL_CANDIDATES=0|off|none  -> legacy namespace for T1
    POLYMER_EXTERNAL_CANDIDATES=<path>      -> use that candidate table instead

A lever whose table is missing is reported in ``skipped`` and left off; a
silently different namespace would make two runs with different coverage look
identical.  ``Registry(**registry_options())`` is the only consumer, and the
passport records the lever state it ran with (``polymer/passport.py``).
"""
from __future__ import annotations
import os
from pathlib import Path

from .common import ROOT

ENV_FLAG = 'POLYMER_PARSE_LEVERS'
ENV_EXTERNAL = 'POLYMER_EXTERNAL_CANDIDATES'
TRUTHY = ('1', 'true', 'yes', 'on')
FALSY = ('0', 'false', 'no', 'off', 'none')
EXTERNAL_DEFAULT = ROOT / 'data/external_candidate_bindings.jsonl'
REPAIR_DEFAULT = ROOT / 'data/repair_declarations.json'
DEFAULT_NAMESPACE = 'DECLARED_LEVERS'
LEGACY_NAMESPACE = 'LEGACY_NAMESPACE'


def _on(value):
    return str(value or '').strip().lower() in TRUTHY


def _off(value):
    """True only for an explicit falsy value; an unset variable is not ``off``."""
    return str(value or '').strip().lower() in FALSY


def _resolve(value):
    path = Path(str(value).strip())
    return path if path.is_absolute() else (ROOT / path)


def evaluate(environ=None):
    """Return ``(registry_options, status)`` for the current environment.

    Nothing set means *all three levers on*; only an explicit
    ``0|off|false|no|none`` puts a lever back on the legacy namespace, which is
    the only configuration in which ``registry_options() == {}`` holds.
    """
    env = os.environ if environ is None else environ
    options, enabled, skipped = {}, [], []
    flag = env.get(ENV_FLAG)
    if not _off(flag):
        options['declared_variants'] = True
        enabled.append({'lever': 'T3', 'table': 'polymer/locant_variants.py',
                        'how': 'explicit' if _on(flag) else 'default'})
        if REPAIR_DEFAULT.is_file():
            options['declared_repairs'] = str(REPAIR_DEFAULT)
            enabled.append({'lever': 'T2', 'table': str(REPAIR_DEFAULT),
                            'how': 'explicit' if _on(flag) else 'default'})
        else:
            skipped.append({'lever': 'T2', 'reason': 'DECLARATION_FILE_MISSING',
                            'path': str(REPAIR_DEFAULT)})
    else:
        skipped.append({'lever': 'T3', 'reason': 'SWITCHED_OFF_BY_ENVIRONMENT',
                        'path': 'polymer/locant_variants.py'})
        skipped.append({'lever': 'T2', 'reason': 'SWITCHED_OFF_BY_ENVIRONMENT',
                        'path': str(REPAIR_DEFAULT)})
    requested = str(env.get(ENV_EXTERNAL) or '').strip()
    if _off(env.get(ENV_EXTERNAL)):
        skipped.append({'lever': 'T1', 'reason': 'SWITCHED_OFF_BY_ENVIRONMENT',
                        'path': requested})
    else:
        path = _resolve(requested) if requested else EXTERNAL_DEFAULT
        if path.is_file():
            options['external_candidates'] = str(path)
            enabled.append({'lever': 'T1', 'table': str(path),
                            'how': 'explicit' if requested else 'default'})
        else:
            skipped.append({'lever': 'T1', 'reason': 'CANDIDATE_TABLE_MISSING',
                            'path': str(path)})
    return options, {'namespace': DEFAULT_NAMESPACE if options else LEGACY_NAMESPACE,
                     'levers_default_on': True, 'enabled': enabled, 'skipped': skipped,
                     'flag': ENV_FLAG, 'external_env': ENV_EXTERNAL,
                     'default_namespace_unchanged': not options}


def registry_options(environ=None):
    """``Registry(...)`` keyword arguments for the current environment."""
    return evaluate(environ)[0]


def status(environ=None):
    """Human-readable description of which levers are on (for startup output)."""
    return evaluate(environ)[1]
