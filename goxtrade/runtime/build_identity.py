"""Source identity for detecting workers left on an older in-memory build."""
import hashlib
from goxtrade.paths import ROOT


def fingerprint(root=None):
    root=root or ROOT/'goxtrade'
    digest=hashlib.sha256()
    for path in sorted(root.rglob('*.py')):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()
