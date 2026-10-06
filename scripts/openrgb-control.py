#!/usr/bin/env python3
"""Backend for the standalone Caelestia OpenRGB plugin.

OpenRGB owns the hardware. This is the thin, machine-readable boundary the
shell talks to, so the QML side never has to know the SDK protocol, the
config layout, or which devices a given host happens to have.

Every command prints a single JSON status object on stdout and exits 0 even
when nothing is available, because the Colours page has to keep rendering on
a machine with no RGB hardware at all.

    caelestia-openrgb status
    caelestia-openrgb apply
    caelestia-openrgb set-mode accent|custom|profile|off
    caelestia-openrgb set-color RRGGBB
    caelestia-openrgb set-brightness 0-100
    caelestia-openrgb set-device <key> on|off
    caelestia-openrgb set-profile <name>
"""

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
STATE_FILE = HOME / ".config" / "caelestia" / "rgb.json"
SCHEME_FILE = HOME / ".local" / "state" / "caelestia" / "scheme.json"
OPENRGB_CONFIG = HOME / ".config" / "OpenRGB"
SERVER_UNIT = "openrgb-server.service"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 6742

MODES = ("accent", "custom", "profile", "off")
DEFAULT_STATE = {
    "mode": "accent",
    "customColor": "cba6f7",
    "brightness": 100,
    "profile": "",
    # Device keys the user has switched off. Keys carry the hardware location,
    # so a list synced from the other machine simply never matches here.
    "disabledDevices": [],
}

# OpenRGB mode flag. Only modes carrying it can actually take a brightness
# value; everything else has to be reported as unsupported rather than faked.
MODE_FLAG_HAS_BRIGHTNESS = 1 << 4

# Preference order for the mode used to paint a solid colour. Direct writes
# straight to the LEDs without touching device flash; Static is the fallback
# for controllers that have no Direct mode (ASRock Polychrome, for one).
COLOUR_MODES = ("direct", "static", "custom")


def load_state():
    state = dict(DEFAULT_STATE)
    try:
        stored = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return state
    if not isinstance(stored, dict):
        return state
    for key in DEFAULT_STATE:
        if key in stored:
            state[key] = stored[key]
    if state["mode"] not in MODES:
        state["mode"] = DEFAULT_STATE["mode"]
    if not isinstance(state["disabledDevices"], list):
        state["disabledDevices"] = []
    state["brightness"] = clamp_percent(state["brightness"])
    state["customColor"] = normalise_hex(state["customColor"]) or DEFAULT_STATE["customColor"]
    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=4) + "\n")


def clamp_percent(value):
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 100


def normalise_hex(value):
    if not isinstance(value, str):
        return ""
    text = value.strip().lstrip("#").lower()
    if len(text) != 6:
        return ""
    try:
        int(text, 16)
    except ValueError:
        return ""
    return text


def accent_hex():
    """The one system accent, read from the scheme the shell itself renders.

    apply_color_overrides.py has already folded any manual accent override and
    the wallpaper-derived palette into this file, so following it keeps RGB on
    the existing accent source instead of inventing a second one.
    """
    try:
        scheme = json.loads(SCHEME_FILE.read_text())
    except (OSError, ValueError):
        return ""
    return normalise_hex(scheme.get("colours", {}).get("primary", ""))


def hex_to_rgb(text):
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def device_key(device):
    """Stable identity for a controller across restarts.

    Name alone collides (two identical DIMMs), so the hardware location is
    appended; that also makes a key from the other machine harmless here.
    """
    location = ""
    metadata = getattr(device, "metadata", None)
    if metadata is not None:
        location = getattr(metadata, "location", "") or ""
    return f"{device.name}@{location}" if location else device.name


def mode_flags(mode):
    flags = getattr(mode, "flags", 0)
    try:
        return int(flags)
    except (TypeError, ValueError):
        return 0


def find_mode(device, names):
    for wanted in names:
        for mode in device.modes:
            if mode.name.strip().lower() == wanted:
                return mode
    return None


def supports_brightness(device):
    mode = find_mode(device, COLOUR_MODES)
    if mode is None:
        return False
    return bool(mode_flags(mode) & MODE_FLAG_HAS_BRIGHTNESS)


def server_reachable():
    try:
        with socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=0.75):
            return True
    except OSError:
        return False


def start_server():
    """Nudge the SDK server up if it is installed but not listening.

    Keeps the Colours page working after an OpenRGB crash or a first run
    before the unit was enabled, without the user opening any GUI.
    """
    if not shutil.which("openrgb"):
        return False
    subprocess.run(
        ["systemctl", "--user", "start", SERVER_UNIT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    for _ in range(12):
        if server_reachable():
            return True
        time.sleep(0.25)
    return False


def connect():
    """Return (client, reason). client is None whenever RGB is unavailable."""
    if not shutil.which("openrgb"):
        return None, "not_installed"
    try:
        from openrgb import OpenRGBClient
    except ImportError:
        return None, "sdk_missing"

    if not server_reachable() and not start_server():
        return None, "server_unavailable"

    try:
        client = OpenRGBClient(SERVER_HOST, SERVER_PORT, "Caelestia")
    except Exception:
        return None, "server_unavailable"
    return client, "ok"


def list_profiles(client):
    """Profiles as OpenRGB itself reports them, not parsed out of its config."""
    try:
        profiles = client.profiles
    except Exception:
        return []
    names = []
    for profile in profiles:
        name = getattr(profile, "name", profile)
        if isinstance(name, str) and name:
            names.append(name)
    return sorted(names)


def describe_devices(client, state):
    disabled = set(state["disabledDevices"])
    devices = []
    for index, device in enumerate(client.devices):
        key = device_key(device)
        raw_type = getattr(getattr(device, "type", None), "name", "") or ""
        # Keep short names as the acronyms they are (DRAM, GPU) and only
        # sentence-case the longer ones (MOTHERBOARD -> Motherboard).
        type_name = raw_type if len(raw_type) <= 4 else raw_type.replace("_", " ").capitalize()
        devices.append({
            "index": index,
            "key": key,
            "name": device.name,
            "type": type_name,
            "enabled": key not in disabled,
            "supportsColour": find_mode(device, COLOUR_MODES) is not None,
            "supportsBrightness": supports_brightness(device),
            "supportsOff": find_mode(device, ("off",)) is not None,
            "modes": [mode.name for mode in device.modes],
        })
    return devices


def apply_brightness(device, mode, percent):
    """Set hardware brightness, and report whether the device took it."""
    if not (mode_flags(mode) & MODE_FLAG_HAS_BRIGHTNESS):
        return False
    low = getattr(mode, "brightness_min", 0) or 0
    high = getattr(mode, "brightness_max", 100)
    if high is None:
        high = 100
    mode.brightness = int(round(low + (high - low) * percent / 100))
    return True


def paint(device, rgb, brightness):
    from openrgb.utils import RGBColor

    mode = find_mode(device, COLOUR_MODES)
    if mode is None:
        return False
    # Devices without brightness support get the colour exactly as chosen,
    # rather than a dimmed approximation of a control they do not have.
    apply_brightness(device, mode, brightness)
    device.set_mode(mode)
    device.set_color(RGBColor(*rgb))
    return True


def turn_off(device):
    from openrgb.utils import RGBColor

    off = find_mode(device, ("off",))
    if off is not None:
        device.set_mode(off)
        return True
    # No Off mode: black in the colour mode is the closest honest equivalent.
    mode = find_mode(device, COLOUR_MODES)
    if mode is None:
        return False
    device.set_mode(mode)
    device.set_color(RGBColor(0, 0, 0))
    return True


def apply_state(client, state):
    """Push the persisted intent to the hardware. Returns a per-device report."""
    disabled = set(state["disabledDevices"])
    applied = []

    if state["mode"] == "profile":
        name = state["profile"]
        if name and name in list_profiles(client):
            try:
                client.load_profile(name)
                return {"profileLoaded": name, "devices": applied}
            except Exception:
                return {"profileLoaded": "", "error": "profile_failed", "devices": applied}
        return {"profileLoaded": "", "error": "profile_missing", "devices": applied}

    if state["mode"] == "accent":
        colour = accent_hex() or state["customColor"]
    else:
        colour = state["customColor"]
    rgb = hex_to_rgb(colour)

    for device in client.devices:
        key = device_key(device)
        if key in disabled:
            # Excluded devices are switched off rather than left on a stale
            # colour, which is what "not part of the global setting" means here.
            try:
                turn_off(device)
            except Exception:
                pass
            continue
        try:
            if state["mode"] == "off":
                ok = turn_off(device)
            else:
                ok = paint(device, rgb, state["brightness"])
        except Exception:
            ok = False
        applied.append({"key": key, "ok": ok})

    return {"devices": applied}


def build_status(state, client, reason, result=None):
    status = {
        "available": client is not None,
        "reason": reason,
        "state": state,
        "accent": accent_hex(),
        "devices": [],
        "profiles": [],
        "host": socket.gethostname(),
    }
    if client is not None:
        status["devices"] = describe_devices(client, state)
        status["profiles"] = list_profiles(client)
        if not status["devices"]:
            status["reason"] = "no_devices"
    if result:
        status["result"] = result
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("apply")
    sub.add_parser("devices")
    p = sub.add_parser("set-mode")
    p.add_argument("value", choices=MODES)
    p = sub.add_parser("set-color")
    p.add_argument("value")
    p = sub.add_parser("set-brightness")
    p.add_argument("value")
    p = sub.add_parser("set-device")
    p.add_argument("key")
    p.add_argument("value", choices=("on", "off"))
    p = sub.add_parser("set-profile")
    p.add_argument("value")
    args = parser.parse_args()

    state = load_state()
    mutated = False

    if args.command == "set-mode":
        state["mode"] = args.value
        mutated = True
    elif args.command == "set-color":
        colour = normalise_hex(args.value)
        if colour:
            state["customColor"] = colour
            mutated = True
    elif args.command == "set-brightness":
        state["brightness"] = clamp_percent(args.value)
        mutated = True
    elif args.command == "set-device":
        disabled = [k for k in state["disabledDevices"] if k != args.key]
        if args.value == "off":
            disabled.append(args.key)
        state["disabledDevices"] = disabled
        mutated = True
    elif args.command == "set-profile":
        state["profile"] = args.value
        mutated = True

    if mutated:
        save_state(state)

    client, reason = connect()
    result = None
    if client is not None and args.command != "devices":
        if args.command in ("apply", "set-mode", "set-color", "set-brightness",
                            "set-device", "set-profile"):
            result = apply_state(client, state)

    status = build_status(state, client, reason, result)
    if args.command == "devices":
        status = {"available": status["available"], "reason": status["reason"],
                  "devices": status["devices"]}

    json.dump(status, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # The Colours page must never see a crash.
        json.dump({"available": False, "reason": "error", "error": str(exc),
                   "state": DEFAULT_STATE, "devices": [], "profiles": []}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(0)
