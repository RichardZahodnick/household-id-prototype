"""Loads config.json and applies command-line overrides."""
import json
import os

DAY = 86400  # seconds


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_override(cfg, text):
    """Apply one 'dotted.key=value' override, e.g. 'ip_changes.speed=4'."""
    if "=" not in text:
        raise ValueError("Override must look like key=value, got: %s" % text)
    key, raw = text.split("=", 1)
    parts = key.strip().split(".")
    node = cfg
    for p in parts[:-1]:
        if p not in node or not isinstance(node[p], dict):
            raise ValueError("Unknown setting: %s" % key)
        node = node[p]
    leaf = parts[-1]
    if leaf not in node:
        raise ValueError("Unknown setting: %s" % key)
    old = node[leaf]
    raw = raw.strip()
    if isinstance(old, bool):
        value = raw.lower() in ("1", "true", "yes")
    elif isinstance(old, int):
        value = int(float(raw))
    elif isinstance(old, float):
        value = float(raw)
    else:
        value = raw
    node[leaf] = value
    return key.strip(), old, value


def default_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config.json")
