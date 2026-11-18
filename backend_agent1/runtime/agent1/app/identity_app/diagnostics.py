"""Mechanical context for existing exceptions; never change acceptance or facts."""

def ordered(values):
    return sorted(values, key=str)


def reference_set(value):
    """Only for diagnostic projection; original validation still handles types."""
    try:
        return set(value or [])
    except TypeError:
        return set()


def attach(exc, **context):
    try:
        diagnostics = getattr(exc, 'diagnostics', [])
        exc.diagnostics = [*(diagnostics if isinstance(diagnostics, list) else []), context]
    except Exception:
        # An unusual exception object must retain its original class/text too.
        pass
    return exc


def fail(code, **context):
    raise attach(ValueError(code), code=code, **context)


def failure_result(exc):
    result = {'status': 'TOOL_FAILED', 'error': type(exc).__name__ + ': ' + str(exc)}
    try:
        diagnostics = getattr(exc, 'diagnostics', None)
    except Exception:
        diagnostics = None
    if diagnostics:
        result['diagnostics'] = diagnostics
    return result
