"""Study commitments are explicit and never inferred from a fixed old directory."""
import hashlib
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hashes(directory):
    root = Path(directory).resolve()
    paths = sorted(root.rglob('*'))
    require(not any(path.is_symlink() for path in paths), 'packet contains a symlink')
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def verify_packet(packet, commitment):
    packet = Path(packet).resolve()
    records = json.loads(Path(commitment).read_text())
    name = packet.name
    require(name in records['packets'], 'packet is absent from this study commitment')
    require(hashes(packet) == records['packets'][name]['hashes'], 'committed packet hash mismatch: ' + name)
    require(records['packets'][name]['grade'] in ('S','B','C'), 'unsupported structural family')
    return name


def verify_release(freeze):
    root = Path(__file__).resolve().parents[1]
    records = json.loads(Path(freeze).read_text())
    for name, expected in records['files'].items():
        path = (root / name).resolve()
        require(path.is_relative_to(root), 'external source in release freeze')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'release source changed: ' + name)
    return hashlib.sha256(Path(freeze).read_bytes()).hexdigest()
