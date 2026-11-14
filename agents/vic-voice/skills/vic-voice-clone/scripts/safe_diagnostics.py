"""Local diagnostics protection; never emits raw CLI error URLs."""
import json
import re

# Redact every URL/query value, including authuser and unfamiliar future keys.
_QUERY = re.compile(r'([?&][^\s?&=\"\'<>]+\s*=)([^\s&\"\'<>]*)')
_BEARER = re.compile(r'(\bBearer\s+)[A-Za-z0-9._~+/=-]+', re.I)
_NAMED = re.compile(r'((?:token|password|secret|api[_-]?key|authorization)\s*[:=]\s*)([^\s,;\"\'<>]+)', re.I)

def redact(value):
    text = str(value)
    text = _QUERY.sub(lambda m: m.group(1) + '[REDACTED]', text)
    text = _BEARER.sub(lambda m: m.group(1) + '[REDACTED]', text)
    return _NAMED.sub(lambda m: m.group(1) + '[REDACTED]', text)

def safe_value(data):
    if isinstance(data, str):
        return redact(data)
    if isinstance(data, dict):
        return {k: ('[REDACTED]' if re.search(r'token|password|secret|api[_-]?key|authorization', str(k), re.I) else safe_value(v)) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [safe_value(v) for v in data]
    return data

def safe_json(data, **kwargs):
    return json.dumps(safe_value(data), **kwargs)

class SafeLineStream:
    """Hold incomplete lines so split query names/values never leak."""
    def __init__(self, emit):
        self.pending = ''
        self.emit = emit
    def feed(self, text, final=False):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            self.emit(redact(line + '\n'))
        if final and self.pending:
            self.emit(redact(self.pending))
            self.pending = ''
