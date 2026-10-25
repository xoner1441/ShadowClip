import base64
import ctypes
import hashlib
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import platform
import struct
import uuid
import wave
import zipfile
import zlib
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

try:
    import winsound
except Exception:
    winsound = None

try:
    import numpy as np
    import soundcard as sc
except Exception:
    np = None
    sc = None


APP_NAME = "ShadowClip"
APP_VERSION = "0.1.23-rc11"
UPDATE_REPO = "xoner1441/ShadowClip"
UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
UPDATE_ASSET_PREFIX = "ShadowClipSetup"
EVENT_SOUND_FILES = {
    "clip": "assets/sounds/pulse_deep_clip.wav",
    "record": "assets/sounds/pulse_deep_start.wav",
    "replay": "assets/sounds/pulse_deep_start.wav",
    "stop": "assets/sounds/pulse_deep_stop.wav",
    "warning": "assets/sounds/pulse_deep_warning.wav",
}
FEEDBACK_ICON_STYLES = {
    "clip": ("clapper", "#80d51a"),
    "record": ("record", "#ff4f64"),
    "replay": ("replay", "#80d51a"),
    "stop": ("check", "#d7dde7"),
    "warning": ("logs", "#ffbd4a"),
    "check": ("check", "#80d51a"),
}
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "shadowclip.config.json"
APP_ICON_NAME = "ShadowClip.ico"
VIDEO_ENCODER_VALUES = ("auto", "h264_nvenc", "h264_amf", "h264_qsv", "libx264")
HARDWARE_VIDEO_ENCODERS = ("h264_nvenc", "h264_amf", "h264_qsv")
VIDEO_ENCODER_LABELS = {
    "auto": "Auto",
    "h264_nvenc": "NVIDIA NVENC (H.264)",
    "h264_amf": "AMD AMF (H.264)",
    "h264_qsv": "Intel QuickSync (H.264)",
    "libx264": "CPU x264",
}
OBS_SIMPLE_ENCODERS = {
    "h264_nvenc": "nvenc",
    "h264_amf": "amd",
    "h264_qsv": "qsv",
    "libx264": "x264",
}
AUTO_BITRATE_PRESETS = ("balanced", "high", "ultra")
AUTO_BITRATE_PRESET_LABELS = {
    "balanced": "Balanced",
    "high": "High",
    "ultra": "Ultra",
}
AUTO_BITRATE_PRESET_FACTORS = {
    "balanced": 0.8,
    "high": 1.0,
    "ultra": 1.25,
}
MEDIA_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
GAME_PROFILE_SETTING_KEYS = (
    "capture_mode",
    "capture_backend",
    "obs_minecraft_capture_mode",
    "monitor_index",
    "window_title",
    "framerate",
    "clip_seconds",
    "segment_seconds",
    "video_encoder",
    "quality",
    "auto_video_bitrate",
    "auto_bitrate_preset",
    "bitrate_mode",
    "video_bitrate_mbps",
    "max_bitrate_mbps",
    "obs_replay_ram_auto",
    "obs_replay_buffer_mb",
    "container",
    "audio_offset_ms",
    "recording_audio_offset_ms",
)


def normalize_video_encoder(value):
    encoder = str(value or "auto").strip().casefold()
    return encoder if encoder in VIDEO_ENCODER_VALUES else "auto"


def video_encoder_label(encoder):
    return VIDEO_ENCODER_LABELS.get(normalize_video_encoder(encoder), str(encoder or "auto"))


def clamp_int(value, minimum, maximum, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(int(minimum), min(int(maximum), parsed))


def recommended_obs_replay_buffer_mb(clip_seconds, video_bitrate_mbps):
    seconds = clamp_int(clip_seconds, 1, 3600, DEFAULT_CONFIG["clip_seconds"])
    bitrate = clamp_int(video_bitrate_mbps, 1, 500, DEFAULT_CONFIG["video_bitrate_mbps"])
    estimated_mb = (bitrate * seconds) / 8.0
    padded_mb = int(estimated_mb * 1.05) + 64
    rounded_mb = ((padded_mb + 63) // 64) * 64
    return max(64, min(2048, rounded_mb))


def normalize_auto_bitrate_preset(value):
    preset = str(value or "high").strip().casefold()
    return preset if preset in AUTO_BITRATE_PRESETS else "high"


def recommended_video_bitrate_mbps(framerate, width, height, preset="high"):
    fps = clamp_int(framerate, 1, 360, DEFAULT_CONFIG["framerate"])
    video_width = clamp_int(width, 320, 8192, 1920)
    video_height = clamp_int(height, 240, 8192, 1080)
    preset_factor = AUTO_BITRATE_PRESET_FACTORS[normalize_auto_bitrate_preset(preset)]
    pixel_factor = (video_width * video_height) / float(1920 * 1080)
    fps_factor = fps / 60.0
    bitrate = 35.0 * pixel_factor * fps_factor * preset_factor
    return max(5, min(300, int(round(bitrate))))


def recommended_max_bitrate_mbps(target_bitrate_mbps, preset="high"):
    target = clamp_int(target_bitrate_mbps, 1, 300, DEFAULT_CONFIG["video_bitrate_mbps"])
    preset = normalize_auto_bitrate_preset(preset)
    overhead = 1.35 if preset == "ultra" else 1.25
    maximum = int(round(target * overhead))
    return max(target + 5, min(500, maximum))


def resource_path(name):
    local_path = APP_DIR / name
    if local_path.exists():
        return local_path
    bundle_dir = Path(getattr(sys, "_MEIPASS", APP_DIR))
    return bundle_dir / name


def normalize_version_text(value):
    text = str(value or "").strip()
    if text.lower().startswith("v"):
        text = text[1:]
    return text


def version_sort_key(value):
    text = normalize_version_text(value).casefold()
    match = re.match(
        r"^(\d+(?:\.\d+){0,3})(?:[-._]?([a-z]+)(?:[-._]?(\d+))?)?",
        text,
    )
    if not match:
        return (0, 0, 0, 0, -1, 0)

    numbers = [int(part) for part in match.group(1).split(".")[:4]]
    numbers.extend([0] * (4 - len(numbers)))
    label = str(match.group(2) or "")
    prerelease_number = int(match.group(3) or 0)
    if not label:
        stage = 4
    else:
        stage = {
            "dev": 0,
            "alpha": 1,
            "a": 1,
            "beta": 2,
            "b": 2,
            "preview": 2,
            "pre": 2,
            "rc": 3,
        }.get(label, 0)
    return tuple(numbers + [stage, prerelease_number])


def is_newer_version(remote_version, current_version):
    return version_sort_key(remote_version) > version_sort_key(current_version)


def format_bytes(size):
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "unknown size"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def fetch_latest_release():
    request = urllib.request.Request(
        UPDATE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def choose_update_asset(release):
    assets = release.get("assets") or []
    candidates = []
    for asset in assets:
        name = str(asset.get("name", ""))
        lower = name.casefold()
        if lower.endswith(".exe") and "shadowclip" in lower and "setup" in lower:
            candidates.append(asset)
    for asset in candidates:
        if str(asset.get("name", "")).casefold().startswith(UPDATE_ASSET_PREFIX.casefold()):
            return asset
    return candidates[0] if candidates else None


def parse_asset_sha256(asset):
    digest = str(asset.get("digest", "") or "")
    if digest.casefold().startswith("sha256:"):
        value = digest.split(":", 1)[1].strip().casefold()
        if re.fullmatch(r"[0-9a-f]{64}", value):
            return value
    return ""


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png_paeth_predictor(left, above, upper_left):
    estimate = left + above - upper_left
    distance_left = abs(estimate - left)
    distance_above = abs(estimate - above)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_above and distance_left <= distance_upper_left:
        return left
    if distance_above <= distance_upper_left:
        return above
    return upper_left


def png_visual_metrics(image_data):
    """Return inexpensive brightness metrics for an OBS PNG screenshot."""
    if not image_data:
        return None
    if isinstance(image_data, str):
        encoded = image_data.split(",", 1)[-1]
        raw_png = base64.b64decode(encoded, validate=False)
    else:
        raw_png = bytes(image_data)
    if not raw_png.startswith(b"\x89PNG\r\n\x1a\n"):
        return None

    width = height = bit_depth = color_type = interlace = 0
    compressed = bytearray()
    palette = []
    offset = 8
    while offset + 12 <= len(raw_png):
        length = struct.unpack(">I", raw_png[offset:offset + 4])[0]
        chunk_type = raw_png[offset + 4:offset + 8]
        chunk_data = raw_png[offset + 8:offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR" and len(chunk_data) >= 13:
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk_data[:13])
        elif chunk_type == b"PLTE":
            palette = [tuple(chunk_data[index:index + 3]) for index in range(0, len(chunk_data) - 2, 3)]
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if not channels or bit_depth != 8 or interlace != 0 or width <= 0 or height <= 0:
        return None
    row_bytes = width * channels
    decoded = zlib.decompress(bytes(compressed))
    expected_size = height * (row_bytes + 1)
    if len(decoded) < expected_size:
        return None

    rows = []
    previous = bytearray(row_bytes)
    cursor = 0
    for _ in range(height):
        filter_type = decoded[cursor]
        cursor += 1
        source = decoded[cursor:cursor + row_bytes]
        cursor += row_bytes
        row = bytearray(row_bytes)
        for index, value in enumerate(source):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                restored = value
            elif filter_type == 1:
                restored = value + left
            elif filter_type == 2:
                restored = value + above
            elif filter_type == 3:
                restored = value + ((left + above) // 2)
            elif filter_type == 4:
                restored = value + _png_paeth_predictor(left, above, upper_left)
            else:
                return None
            row[index] = restored & 0xFF
        rows.append(row)
        previous = row

    total_pixels = width * height
    sample_step = max(1, total_pixels // 16000)
    sampled = 0
    luma_sum = 0.0
    non_dark = 0
    peak = 0
    for pixel_index in range(0, total_pixels, sample_step):
        row = rows[pixel_index // width]
        column = pixel_index % width
        base = column * channels
        if color_type in {0, 4}:
            red = green = blue = row[base]
        elif color_type == 3:
            palette_index = row[base]
            red, green, blue = palette[palette_index] if palette_index < len(palette) else (0, 0, 0)
        else:
            red, green, blue = row[base:base + 3]
        luma = int((54 * red + 183 * green + 19 * blue) / 256)
        sampled += 1
        luma_sum += luma
        peak = max(peak, luma)
        if luma > 16:
            non_dark += 1
    if not sampled:
        return None
    mean_luma = luma_sum / sampled
    non_dark_ratio = non_dark / sampled
    return {
        "width": width,
        "height": height,
        "samples": sampled,
        "mean_luma": mean_luma,
        "non_dark_ratio": non_dark_ratio,
        "peak_luma": peak,
        "black": mean_luma <= 6.0 and non_dark_ratio <= 0.03,
    }


DEFAULT_CONFIG = {
    # Existing configurations inherit True. The installer explicitly writes False
    # so only genuinely new installations open the setup wizard automatically.
    "setup_completed": True,
    "setup_version": "",
    "beta_install_id": "",
    "ffmpeg_path": "",
    "obs_path": "",
    "obs_websocket_port": 4457,
    "obs_websocket_password": "ShadowClipLocal123",
    "output_dir": "%USERPROFILE%\\Videos\\ShadowClip",
    "capture_mode": "desktop_all",
    "capture_backend": "obs",
    "obs_minecraft_capture_mode": "specific_game",
    "capture_desktop_overlays": True,
    "capture_desktop_overlays_migrated": True,
    "monitor_index": 0,
    "window_title": "",
    "framerate": 60,
    "clip_seconds": 30,
    "segment_seconds": 4,
    "video_encoder": "auto",
    "quality": 23,
    "auto_video_bitrate": True,
    "auto_bitrate_preset": "high",
    "bitrate_mode": "target",
    "video_bitrate_mbps": 35,
    "max_bitrate_mbps": 50,
    "obs_replay_ram_auto": True,
    "obs_replay_buffer_mb": 256,
    "audio_mode": "none",
    "audio_device": "",
    "mic_enabled": False,
    "mic_device": "",
    "desktop_audio_enabled": False,
    "desktop_audio_backend": "wasapi",
    "desktop_audio_device": "",
    "audio_offset_ms": -250,
    "recording_audio_offset_ms": -250,
    "start_with_windows": False,
    "auto_start_replay": False,
    "use_game_profiles": True,
    "game_profiles": {},
    "organize_clips_by_game": True,
    "max_storage_gb": 0,
    "container": "mp4",
    "reset_replay_after_clip": True,
    "toast_duration_ms": 2600,
    "toast_position": "top_right",
    "gallery_limit": 12,
    "hide_overlay_after_clip": True,
    "recording_indicator_enabled": True,
    "fullscreen_safe_hud": True,
    "event_sounds_enabled": True,
    "replay_auto_restart": True,
    "replay_max_restarts": 3,
    "check_updates_on_start": True,
    "hotkeys": {
        "save_clip": "F9",
        "toggle_replay": "F10",
        "toggle_recording": "F11",
        "toggle_overlay": "F8",
        "make_borderless": "F12"
    }
}


HOTKEY_ACTIONS = [
    ("toggle_overlay", "Open/close HUD"),
    ("save_clip", "Save clip"),
    ("toggle_replay", "Toggle replay"),
    ("toggle_recording", "Toggle recording"),
    ("make_borderless", "Make Minecraft borderless"),
]

HOTKEY_ACTION_LABELS = dict(HOTKEY_ACTIONS)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_INJECTED = 0x00000010
VK_MENU = 0x12
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C

HOTKEY_MODIFIERS = {
    "ALT": (MOD_ALT, "Alt"),
    "CTRL": (MOD_CONTROL, "Ctrl"),
    "CONTROL": (MOD_CONTROL, "Ctrl"),
    "SHIFT": (MOD_SHIFT, "Shift"),
    "WIN": (MOD_WIN, "Win"),
    "WINDOWS": (MOD_WIN, "Win"),
    "SUPER": (MOD_WIN, "Win"),
    "META": (MOD_WIN, "Win"),
}

HOTKEY_MODIFIER_ORDER = [
    (MOD_CONTROL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Shift"),
    (MOD_WIN, "Win"),
]

SPECIAL_VK = {
    "BACKSPACE": (0x08, "Backspace"),
    "TAB": (0x09, "Tab"),
    "ENTER": (0x0D, "Enter"),
    "RETURN": (0x0D, "Enter"),
    "PAUSE": (0x13, "Pause"),
    "BREAK": (0x13, "Pause"),
    "CAPSLOCK": (0x14, "CapsLock"),
    "CAPS": (0x14, "CapsLock"),
    "ESC": (0x1B, "Esc"),
    "ESCAPE": (0x1B, "Esc"),
    "SPACE": (0x20, "Space"),
    "PAGEUP": (0x21, "PageUp"),
    "PRIOR": (0x21, "PageUp"),
    "PAGEDOWN": (0x22, "PageDown"),
    "NEXT": (0x22, "PageDown"),
    "END": (0x23, "End"),
    "HOME": (0x24, "Home"),
    "LEFT": (0x25, "Left"),
    "UP": (0x26, "Up"),
    "RIGHT": (0x27, "Right"),
    "DOWN": (0x28, "Down"),
    "INSERT": (0x2D, "Insert"),
    "INS": (0x2D, "Insert"),
    "DELETE": (0x2E, "Delete"),
    "DEL": (0x2E, "Delete"),
    "PRINTSCREEN": (0x2C, "PrintScreen"),
    "PRINT": (0x2C, "PrintScreen"),
    "PRTSC": (0x2C, "PrintScreen"),
    "PRTSCR": (0x2C, "PrintScreen"),
    "SNAPSHOT": (0x2C, "PrintScreen"),
    "APPS": (0x5D, "Apps"),
    "CONTEXTMENU": (0x5D, "Apps"),
    "NUMLOCK": (0x90, "NumLock"),
    "SCROLLLOCK": (0x91, "ScrollLock"),
    "NUMPAD0": (0x60, "Numpad0"),
    "NUM0": (0x60, "Numpad0"),
    "KP0": (0x60, "Numpad0"),
    "NUMPAD1": (0x61, "Numpad1"),
    "NUM1": (0x61, "Numpad1"),
    "KP1": (0x61, "Numpad1"),
    "NUMPAD2": (0x62, "Numpad2"),
    "NUM2": (0x62, "Numpad2"),
    "KP2": (0x62, "Numpad2"),
    "NUMPAD3": (0x63, "Numpad3"),
    "NUM3": (0x63, "Numpad3"),
    "KP3": (0x63, "Numpad3"),
    "NUMPAD4": (0x64, "Numpad4"),
    "NUM4": (0x64, "Numpad4"),
    "KP4": (0x64, "Numpad4"),
    "NUMPAD5": (0x65, "Numpad5"),
    "NUM5": (0x65, "Numpad5"),
    "KP5": (0x65, "Numpad5"),
    "NUMPAD6": (0x66, "Numpad6"),
    "NUM6": (0x66, "Numpad6"),
    "KP6": (0x66, "Numpad6"),
    "NUMPAD7": (0x67, "Numpad7"),
    "NUM7": (0x67, "Numpad7"),
    "KP7": (0x67, "Numpad7"),
    "NUMPAD8": (0x68, "Numpad8"),
    "NUM8": (0x68, "Numpad8"),
    "KP8": (0x68, "Numpad8"),
    "NUMPAD9": (0x69, "Numpad9"),
    "NUM9": (0x69, "Numpad9"),
    "KP9": (0x69, "Numpad9"),
    "NUMPADMULTIPLY": (0x6A, "NumpadMultiply"),
    "KPMULTIPLY": (0x6A, "NumpadMultiply"),
    "NUMPADADD": (0x6B, "NumpadAdd"),
    "KPADD": (0x6B, "NumpadAdd"),
    "NUMPADPLUS": (0x6B, "NumpadAdd"),
    "NUMPADSUBTRACT": (0x6D, "NumpadSubtract"),
    "KPSUBTRACT": (0x6D, "NumpadSubtract"),
    "NUMPADMINUS": (0x6D, "NumpadSubtract"),
    "NUMPADDECIMAL": (0x6E, "NumpadDecimal"),
    "KPDECIMAL": (0x6E, "NumpadDecimal"),
    "NUMPADDIVIDE": (0x6F, "NumpadDivide"),
    "KPDIVIDE": (0x6F, "NumpadDivide"),
    "SEMICOLON": (0xBA, "Semicolon"),
    ";": (0xBA, "Semicolon"),
    "PLUS": (0xBB, "Plus"),
    "EQUALS": (0xBB, "Plus"),
    "EQUAL": (0xBB, "Plus"),
    "=": (0xBB, "Plus"),
    "COMMA": (0xBC, "Comma"),
    ",": (0xBC, "Comma"),
    "MINUS": (0xBD, "Minus"),
    "DASH": (0xBD, "Minus"),
    "-": (0xBD, "Minus"),
    "PERIOD": (0xBE, "Period"),
    "DOT": (0xBE, "Period"),
    ".": (0xBE, "Period"),
    "SLASH": (0xBF, "Slash"),
    "FORWARDSLASH": (0xBF, "Slash"),
    "/": (0xBF, "Slash"),
    "BACKQUOTE": (0xC0, "Backquote"),
    "GRAVE": (0xC0, "Backquote"),
    "`": (0xC0, "Backquote"),
    "LEFTBRACKET": (0xDB, "LeftBracket"),
    "[": (0xDB, "LeftBracket"),
    "BACKSLASH": (0xDC, "Backslash"),
    "\\": (0xDC, "Backslash"),
    "RIGHTBRACKET": (0xDD, "RightBracket"),
    "]": (0xDD, "RightBracket"),
    "QUOTE": (0xDE, "Quote"),
    "APOSTROPHE": (0xDE, "Quote"),
    "'": (0xDE, "Quote"),
    "VOLUMEMUTE": (0xAD, "VolumeMute"),
    "VOLUMEDOWN": (0xAE, "VolumeDown"),
    "VOLUMEUP": (0xAF, "VolumeUp"),
    "MEDIANEXT": (0xB0, "MediaNext"),
    "MEDIAPREV": (0xB1, "MediaPrev"),
    "MEDIAPREVIOUS": (0xB1, "MediaPrev"),
    "MEDIASTOP": (0xB2, "MediaStop"),
    "MEDIAPLAYPAUSE": (0xB3, "MediaPlayPause"),
    "PLAYPAUSE": (0xB3, "MediaPlayPause"),
}

MODIFIER_KEYSYMS = {
    "Alt_L",
    "Alt_R",
    "Control_L",
    "Control_R",
    "Shift_L",
    "Shift_R",
    "Super_L",
    "Super_R",
    "Meta_L",
    "Meta_R",
    "Win_L",
    "Win_R",
}

TK_KEYSYM_ALIASES = {
    "Escape": "Esc",
    "Return": "Enter",
    "Prior": "PageUp",
    "Next": "PageDown",
    "space": "Space",
    "BackSpace": "Backspace",
    "Delete": "Delete",
    "Insert": "Insert",
    "Print": "PrintScreen",
    "Snapshot": "PrintScreen",
    "Caps_Lock": "CapsLock",
    "Num_Lock": "NumLock",
    "Scroll_Lock": "ScrollLock",
    "Menu": "Apps",
    "KP_0": "Numpad0",
    "KP_1": "Numpad1",
    "KP_2": "Numpad2",
    "KP_3": "Numpad3",
    "KP_4": "Numpad4",
    "KP_5": "Numpad5",
    "KP_6": "Numpad6",
    "KP_7": "Numpad7",
    "KP_8": "Numpad8",
    "KP_9": "Numpad9",
    "KP_Multiply": "NumpadMultiply",
    "KP_Add": "NumpadAdd",
    "KP_Subtract": "NumpadSubtract",
    "KP_Decimal": "NumpadDecimal",
    "KP_Delete": "NumpadDecimal",
    "KP_Divide": "NumpadDivide",
    "semicolon": "Semicolon",
    "plus": "Plus",
    "equal": "Plus",
    "comma": "Comma",
    "minus": "Minus",
    "period": "Period",
    "slash": "Slash",
    "backslash": "Backslash",
    "bracketleft": "LeftBracket",
    "bracketright": "RightBracket",
    "apostrophe": "Quote",
    "quoteleft": "Backquote",
}


def parse_hotkey_text(hotkey_text):
    text = str(hotkey_text or "").strip()
    if not text:
        raise ValueError("Hotkey is empty.")
    parts = [part.strip() for part in re.split(r"\s*\+\s*", text) if part.strip()]
    modifiers = 0
    key_code = None
    key_label = None
    for part in parts:
        token = re.sub(r"[\s_-]+", "", part).upper()
        if token in HOTKEY_MODIFIERS:
            modifiers |= HOTKEY_MODIFIERS[token][0]
            continue
        if key_code is not None:
            raise ValueError(f"Hotkey has more than one key: {text}")
        if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", token):
            number = int(token[1:])
            key_code = 0x70 + number - 1
            key_label = f"F{number}"
        elif re.fullmatch(r"[A-Z]", token):
            key_code = ord(token)
            key_label = token
        elif re.fullmatch(r"[0-9]", token):
            key_code = ord(token)
            key_label = token
        elif token in SPECIAL_VK:
            key_code, key_label = SPECIAL_VK[token]
        else:
            raise ValueError(f"Unknown key: {part}")
    if key_code is None:
        raise ValueError(f"Hotkey needs a key: {text}")
    labels = [label for bit, label in HOTKEY_MODIFIER_ORDER if modifiers & bit]
    labels.append(key_label)
    return modifiers, key_code, "+".join(labels)


def hotkey_from_event(event):
    keysym = str(getattr(event, "keysym", "") or "")
    if not keysym or keysym in MODIFIER_KEYSYMS:
        return ""
    state = int(getattr(event, "state", 0) or 0)
    modifiers = []
    if state & 0x0004:
        modifiers.append("Ctrl")
    if state & 0x0008 or state & 0x20000:
        modifiers.append("Alt")
    if state & 0x0001:
        modifiers.append("Shift")
    if state & 0x0040 or state & 0x0080:
        modifiers.append("Win")

    token = keysym
    if len(token) == 1:
        token = token.upper()
    else:
        token = TK_KEYSYM_ALIASES.get(token, token)
    candidate = "+".join(modifiers + [token])
    try:
        return parse_hotkey_text(candidate)[2]
    except ValueError:
        return candidate


def normalize_hotkey_config(hotkeys):
    source = DEFAULT_CONFIG["hotkeys"].copy()
    if isinstance(hotkeys, dict):
        source.update(hotkeys)
    normalized = {}
    for action, _label in HOTKEY_ACTIONS:
        normalized[action] = parse_hotkey_text(source.get(action, DEFAULT_CONFIG["hotkeys"][action]))[2]
    return normalized


ICONS = {
    "app": "◆",
    "audio": "♪",
    "backend": "◇",
    "browse": "…",
    "clean": "⌫",
    "clip": "▣",
    "close": "×",
    "container": "▥",
    "desktop": "▦",
    "ffmpeg": "ƒ",
    "folder": "▤",
    "gallery": "▧",
    "hotkey": "⌨",
    "mic": "◉",
    "monitor": "▣",
    "play": "▶",
    "quality": "▨",
    "record": "●",
    "replay": "↻",
    "settings": "⚙",
    "source": "⌖",
    "startup": "↥",
    "stop": "■",
    "storage": "▤",
    "tray": "▾",
    "video": "▥",
    "window": "□",
}


def ui_text(icon_key, label):
    icon = ICONS.get(icon_key, "")
    return f"{icon}  {label}" if icon else label


def overlay_text(icon_key, title, detail=""):
    icon = ICONS.get(icon_key, "")
    lines = [line for line in (icon, title, detail) if line]
    return "\n".join(lines)


def format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def format_file_size(size):
    size = float(size or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024


def media_kind_for_path(path):
    name = Path(path).stem.casefold().strip()
    if name.startswith("replay") or name.startswith("clip_") or name.startswith("clip "):
        return "replay"
    if name.startswith("recording") or re.match(r"^\d{4}[-_]\d{2}[-_]\d{2}", name):
        return "recording"
    return "video"


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ERROR_ALREADY_EXISTS = 183
FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
if not hasattr(wintypes, "HHOOK"):
    wintypes.HHOOK = wintypes.HANDLE
if not hasattr(wintypes, "HINSTANCE"):
    wintypes.HINSTANCE = wintypes.HANDLE
if not hasattr(wintypes, "HMODULE"):
    wintypes.HMODULE = wintypes.HANDLE
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
LOWLEVELKEYBOARDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class SHFileOperationStruct(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def move_path_to_recycle_bin(path, owner_hwnd=None):
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    if os.name != "nt":
        raise OSError("Recycle Bin is only available on Windows")
    source = ctypes.create_unicode_buffer(f"{path}\0")
    operation = SHFileOperationStruct()
    operation.hwnd = owner_hwnd or None
    operation.wFunc = FO_DELETE
    operation.pFrom = ctypes.cast(source, wintypes.LPCWSTR)
    operation.pTo = None
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    shell32 = ctypes.windll.shell32
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFileOperationStruct)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    result = shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(result, f"Windows could not move the file to the Recycle Bin (code {result})")
    if operation.fAnyOperationsAborted:
        raise OSError("The Recycle Bin operation was cancelled")

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_MOUSEACTIVATE = 0x0021
WM_QUIT = 0x0012
WM_CONTEXTMENU = 0x007B
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_TRAY_NOTIFY = WM_APP + 2
NIN_SELECT = WM_USER
NIN_KEYSELECT = WM_USER + 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
MONITOR_DEFAULTTONEAREST = 2
CCHDEVICENAME = 32
GWL_STYLE = -16
GWL_EXSTYLE = -20
GWLP_WNDPROC = -4
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_WINDOWEDGE = 0x00000100
HWND_TOP = wintypes.HWND(0)
HWND_TOPMOST = wintypes.HWND(-1)
SW_SHOWNORMAL = 1
SW_SHOWNOACTIVATE = 4
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
MA_NOACTIVATE = 3
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_F11 = 0x7A

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NOTIFYICON_VERSION_4 = 4
NIIF_INFO = 0x00000001
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

TRAY_OPEN = 1001
TRAY_HIDE = 1002
TRAY_TOGGLE_REPLAY = 1003
TRAY_SAVE_CLIP = 1004
TRAY_TOGGLE_RECORDING = 1005
TRAY_STOP_ALL = 1006
TRAY_OPEN_OUTPUT = 1007
TRAY_OPEN_LAST_CLIP = 1008
TRAY_SHOW_LAST_CLIP = 1009
TRAY_MAKE_BORDERLESS = 1010
TRAY_EXIT = 1011
SINGLE_INSTANCE_MUTEX_NAME = "Local\\ShadowClip.SingleInstance"
BROWSER_CAPTURE_PROCESSES = {
    "arc",
    "brave",
    "chrome",
    "chromium",
    "firefox",
    "floorp",
    "librewolf",
    "msedge",
    "opera",
    "opera_gx",
    "vivaldi",
    "waterfox",
}
DESKTOP_CAPTURE_PROCESSES = {
    "applicationframehost",
    "explorer",
    "searchhost",
    "shellexperiencehost",
    "startmenuexperiencehost",
    "steamwebhelper",
    "textinputhost",
}
OPENGL_GAME_CAPTURE_PROCESSES = {
    "java",
    "javaw",
    "minecraft",
    "minecraft.windows",
    "minecraftlauncher",
}

FRIENDLY_PROCESS_NAMES = {
    "java": "Minecraft",
    "javaw": "Minecraft",
    "minecraft": "Minecraft",
    "minecraft.windows": "Minecraft Bedrock",
    "minecraftlauncher": "Minecraft Launcher",
    "rustclient": "Rust",
    "leagueclient": "League of Legends",
    "leagueclientux": "League of Legends",
    "league of legends": "League of Legends",
    "rainbowsix": "Rainbow Six Siege",
    "rainbowsix_vulkan": "Rainbow Six Siege",
    "rainbowsixgame": "Rainbow Six Siege",
    "fortniteclient-win64-shipping": "Fortnite",
    "valorant-win64-shipping": "VALORANT",
    "cs2": "Counter-Strike 2",
    "csgo": "Counter-Strike 2",
    "rocketleague": "Rocket League",
    "r5apex": "Apex Legends",
    "overwatch": "Overwatch 2",
    "overwatchlauncher": "Overwatch 2",
    "tslgame": "PUBG Battlegrounds",
    "escapefromtarkov": "Escape from Tarkov",
    "destiny2": "Destiny 2",
    "eldenring": "Elden Ring",
    "helldivers2": "Helldivers 2",
    "dota2": "Dota 2",
    "gta5": "Grand Theft Auto V",
    "gta5_enhanced": "Grand Theft Auto V",
    "cyberpunk2077": "Cyberpunk 2077",
    "witcher3": "The Witcher 3",
    "bg3": "Baldur's Gate 3",
    "bg3_dx11": "Baldur's Gate 3",
    "cod": "Call of Duty",
    "cod22-cod": "Call of Duty",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "firefox": "Mozilla Firefox",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
}

FRIENDLY_TITLE_PATTERNS = (
    (r"\bminecraft\b", "Minecraft"),
    (r"\brust\b", "Rust"),
    (r"league of legends", "League of Legends"),
    (r"rainbow six", "Rainbow Six Siege"),
    (r"\bfortnite\b", "Fortnite"),
    (r"\bvalorant\b", "VALORANT"),
    (r"counter-strike", "Counter-Strike 2"),
    (r"rocket league", "Rocket League"),
    (r"apex legends", "Apex Legends"),
    (r"overwatch", "Overwatch 2"),
    (r"baldur'?s gate 3", "Baldur's Gate 3"),
)


def expand_path(value):
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def timestamp_name(prefix, suffix):
    return f"{prefix}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.{suffix}"


def sanitize_path_part(value, fallback="Desktop"):
    text = str(value or "").strip()
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = fallback
    return text[:80].rstrip(" .") or fallback


def get_window_text(hwnd):
    if os.name != "nt" or not hwnd:
        return ""
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def get_window_class_name(hwnd):
    if os.name != "nt" or not hwnd:
        return ""
    try:
        user32 = ctypes.windll.user32
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        buffer = ctypes.create_unicode_buffer(256)
        if user32.GetClassNameW(wintypes.HWND(int(hwnd)), buffer, len(buffer)):
            return buffer.value.strip()
    except Exception:
        return ""
    return ""


def window_process_name(hwnd):
    if os.name != "nt" or not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).stem
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(handle)
    return ""


def window_process_exe_name(hwnd):
    if os.name != "nt" or not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(handle)
    return ""


def process_name_key(value):
    return Path(str(value or "").strip()).stem.casefold()


def friendly_application_name(process_name="", title="", fallback=""):
    process_key = process_name_key(process_name)
    if process_key in FRIENDLY_PROCESS_NAMES:
        return FRIENDLY_PROCESS_NAMES[process_key]
    title_text = str(title or "").strip()
    title_key = title_text.casefold()
    for pattern, friendly in FRIENDLY_TITLE_PATTERNS:
        if re.search(pattern, title_key, re.IGNORECASE):
            return friendly
    raw = Path(str(process_name or "").strip()).stem or title_text or str(fallback or "").strip()
    cleaned = re.sub(r"(?i)(?:[-_ ]win64)?[-_ ]shipping$", "", raw)
    cleaned = re.sub(r"(?i)[-_ ](?:vulkan|dx11|dx12)$", "", cleaned)
    cleaned = cleaned.replace("_", " ").strip()
    return sanitize_path_part(cleaned, sanitize_path_part(fallback, "Desktop"))


def is_browser_process(value):
    return process_name_key(value) in BROWSER_CAPTURE_PROCESSES


def monitor_bounds_from_window(hwnd):
    if os.name != "nt" or not hwnd:
        return None
    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = user32.MonitorFromWindow(wintypes.HWND(int(hwnd)), MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        rect = info.rcMonitor
        return {
            "left": int(rect.left),
            "top": int(rect.top),
            "width": int(rect.right - rect.left),
            "height": int(rect.bottom - rect.top),
        }
    except Exception:
        return None


def monitor_device_name_from_handle(hmonitor):
    if os.name != "nt" or not hmonitor:
        return ""
    try:
        user32 = ctypes.windll.user32
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfoEx)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        info = MonitorInfoEx()
        info.cbSize = ctypes.sizeof(MonitorInfoEx)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            return str(info.szDevice or "").strip()
    except Exception:
        return ""
    return ""


def monitor_device_name_from_window(hwnd):
    if os.name != "nt" or not hwnd:
        return ""
    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        monitor = user32.MonitorFromWindow(wintypes.HWND(int(hwnd)), MONITOR_DEFAULTTONEAREST)
        return monitor_device_name_from_handle(monitor)
    except Exception:
        return ""


def monitor_device_name_for_index(index):
    if os.name != "nt":
        return ""
    result = {"current": 0, "device": ""}
    target = max(0, int(index or 0))
    user32 = ctypes.windll.user32
    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(Rect),
        wintypes.LPARAM,
    )

    def callback(hmonitor, hdc, rect_ptr, lparam):
        if result["current"] == target:
            result["device"] = monitor_device_name_from_handle(hmonitor)
            return False
        result["current"] += 1
        return True

    try:
        user32.EnumDisplayMonitors(0, 0, monitor_enum_proc(callback), 0)
    except Exception:
        return ""
    return result["device"]


def window_is_fullscreen_like(hwnd):
    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
        user32.GetWindowRect.restype = wintypes.BOOL
        try:
            get_window_long = user32.GetWindowLongPtrW
        except AttributeError:
            get_window_long = user32.GetWindowLongW
        get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_window_long.restype = ctypes.c_ssize_t
        bounds = monitor_bounds_from_window(hwnd)
        if not bounds:
            return False
        rect = Rect()
        if not user32.GetWindowRect(wintypes.HWND(int(hwnd)), ctypes.byref(rect)):
            return False
        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
        tolerance = 4
        strict_fullscreen = (
            left <= bounds["left"] + tolerance
            and top <= bounds["top"] + tolerance
            and right >= bounds["left"] + bounds["width"] - tolerance
            and bottom >= bounds["top"] + bounds["height"] - tolerance
        )
        if strict_fullscreen:
            return True
        style = int(get_window_long(wintypes.HWND(int(hwnd)), GWL_STYLE))
        has_caption = bool(style & WS_CAPTION)
        intersect_left = max(left, bounds["left"])
        intersect_top = max(top, bounds["top"])
        intersect_right = min(right, bounds["left"] + bounds["width"])
        intersect_bottom = min(bottom, bounds["top"] + bounds["height"])
        intersect_area = max(0, intersect_right - intersect_left) * max(0, intersect_bottom - intersect_top)
        monitor_area = max(1, bounds["width"] * bounds["height"])
        return (intersect_area / monitor_area) >= 0.92 and not has_caption
    except Exception:
        return False


def is_opengl_game_context(context):
    if not isinstance(context, dict):
        return False
    process_name = process_name_key(context.get("process"))
    title = str(context.get("title") or "").casefold()
    return process_name in OPENGL_GAME_CAPTURE_PROCESSES or "minecraft" in title


def foreground_window_basic_context():
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        process_name = window_process_name(hwnd)
        ignored_processes = {
            APP_NAME.casefold(),
            Path(sys.executable).stem.casefold(),
        }
        if process_name_key(process_name) in ignored_processes:
            return None
        return {
            "hwnd": int(hwnd),
            "title": get_window_text(hwnd),
            "process": process_name,
            "exe": window_process_exe_name(hwnd),
            "class": get_window_class_name(hwnd),
            "fullscreen": window_is_fullscreen_like(hwnd),
        }
    except Exception:
        return None


def find_window_by_title(title):
    if os.name != "nt" or not title:
        return None
    user32 = ctypes.windll.user32
    target = str(title).strip()
    result = {"hwnd": None}
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, lparam):
        if result["hwnd"]:
            return False
        if user32.IsWindowVisible(hwnd) and get_window_text(hwnd) == target:
            result["hwnd"] = hwnd
            return False
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return result["hwnd"]


def foreground_application_label():
    if os.name != "nt":
        return ""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    process_name = window_process_name(hwnd)
    ignored_processes = {
        APP_NAME.casefold(),
        "applicationframehost",
        "explorer",
        "shellexperiencehost",
        "searchhost",
        "startmenuexperiencehost",
        "steamwebhelper",
        "textinputhost",
    }
    title = get_window_text(hwnd)
    if process_name and process_name.casefold() not in ignored_processes:
        return friendly_application_name(process_name, title, process_name)
    title_key = title.casefold()
    if title and not title_key.startswith(APP_NAME.casefold()):
        return title
    return ""


class BrowseInfo(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wintypes.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", wintypes.LPWSTR),
        ("lpszTitle", wintypes.LPCWSTR),
        ("ulFlags", wintypes.UINT),
        ("lpfn", ctypes.c_void_p),
        ("lParam", wintypes.LPARAM),
        ("iImage", ctypes.c_int),
    ]


def browse_directory_win32(title, owner=None):
    if os.name != "nt":
        return ""

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    display_name = ctypes.create_unicode_buffer(260)
    path_buffer = ctypes.create_unicode_buffer(32768)
    initialized_com = False
    try:
        hr = ole32.CoInitialize(None)
        initialized_com = hr in (0, 1)
    except Exception:
        initialized_com = False

    try:
        info = BrowseInfo()
        info.hwndOwner = wintypes.HWND(owner or 0)
        info.pszDisplayName = ctypes.cast(display_name, wintypes.LPWSTR)
        info.lpszTitle = title
        info.ulFlags = 0x00000001 | 0x00000010 | 0x00000040

        shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
        shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
        shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
        shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return ""
        try:
            if shell32.SHGetPathFromIDListW(pidl, path_buffer):
                return path_buffer.value
            return ""
        finally:
            ole32.CoTaskMemFree(pidl)
    finally:
        if initialized_com:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass


def browse_directory_powershell(title, initial_dir=""):
    if os.name != "nt":
        return ""

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeError("powershell.exe not found")

    script = r"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:SHADOWCLIP_PICKER_TITLE
$dialog.ShowNewFolderButton = $true
if ($env:SHADOWCLIP_INITIAL_DIR -and (Test-Path -LiteralPath $env:SHADOWCLIP_INITIAL_DIR)) {
    $dialog.SelectedPath = $env:SHADOWCLIP_INITIAL_DIR
}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Write($dialog.SelectedPath)
}
"""
    env = os.environ.copy()
    env["SHADOWCLIP_PICKER_TITLE"] = title
    env["SHADOWCLIP_INITIAL_DIR"] = str(initial_dir or "")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-STA",
            "-Command", script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(error or f"PowerShell folder picker exited with code {result.returncode}")
    return result.stdout.strip()


def browse_file_powershell(title, file_filter, initial_dir=""):
    if os.name != "nt":
        return ""

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeError("powershell.exe not found")

    script = r"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = $env:SHADOWCLIP_PICKER_TITLE
$dialog.Filter = $env:SHADOWCLIP_FILE_FILTER
$dialog.CheckFileExists = $true
$dialog.CheckPathExists = $true
if ($env:SHADOWCLIP_INITIAL_DIR -and (Test-Path -LiteralPath $env:SHADOWCLIP_INITIAL_DIR)) {
    $dialog.InitialDirectory = $env:SHADOWCLIP_INITIAL_DIR
}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Write($dialog.FileName)
}
"""
    env = os.environ.copy()
    env["SHADOWCLIP_PICKER_TITLE"] = title
    env["SHADOWCLIP_FILE_FILTER"] = file_filter
    env["SHADOWCLIP_INITIAL_DIR"] = str(initial_dir or "")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-STA",
            "-Command", script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(error or f"PowerShell file picker exited with code {result.returncode}")
    return result.stdout.strip()


def load_config():
    config = DEFAULT_CONFIG.copy()
    config["hotkeys"] = DEFAULT_CONFIG["hotkeys"].copy()
    user_config = {}
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8-sig") as handle:
                user_config = json.load(handle)
            for key, value in user_config.items():
                if key == "hotkeys" and isinstance(value, dict):
                    config["hotkeys"].update(value)
                else:
                    config[key] = value
        except Exception:
            pass
    if "capture_desktop_overlays_migrated" not in user_config:
        config["capture_desktop_overlays"] = True
        config["capture_desktop_overlays_migrated"] = True
    if config.get("audio_mode") == "dshow" and config.get("audio_device") and not config.get("mic_device"):
        config["mic_enabled"] = True
        config["mic_device"] = config["audio_device"]
    beta_install_id = str(config.get("beta_install_id") or "").strip().upper()
    if not re.fullmatch(r"SC-[0-9A-F]{12}", beta_install_id):
        beta_install_id = f"SC-{uuid.uuid4().hex[:12].upper()}"
    config["beta_install_id"] = beta_install_id
    return config


def save_config(config):
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)


def acquire_single_instance_mutex():
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.restype = wintypes.DWORD
    handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
    if not handle:
        return None
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    return handle


def remove_legacy_startup_shortcut():
    if os.name != "nt":
        return
    startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    for name in ("ShadowClip.lnk", "ShadowClip.url"):
        try:
            (startup_dir / name).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def looks_like_desktop_audio_device(name):
    text = name.casefold()
    markers = [
        "stereo mix",
        "stereomix",
        "what u hear",
        "loopback",
        "speaker",
        "speakers",
        "lautsprecher",
        "desktop",
        "output",
        "vb-audio",
        "vb cable",
        "cable output",
        "voicemeeter",
        "wave out",
        "wasapi",
    ]
    return any(marker in text for marker in markers)


def write_float_wav(path, data, sample_rate):
    if np is None:
        raise RuntimeError("NumPy is not available for WAV writing.")
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(int(pcm.shape[1]))
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm.tobytes())


def replace_with_retries(temp_path, target_path, attempts=20, base_delay=0.035):
    last_error = None
    for attempt in range(attempts):
        try:
            temp_path.replace(target_path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(base_delay * min(attempt + 1, 8))
    if last_error:
        raise last_error


def unique_destination_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def explorer_select_parameters(path):
    resolved = Path(path).resolve()
    return f'/select,"{resolved}"'


def reveal_file_in_explorer(path):
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    if os.name != "nt":
        raise OSError("Explorer file selection is only available on Windows")
    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    parameters = explorer_select_parameters(path)
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    result = shell32.ShellExecuteW(
        None,
        "open",
        str(explorer),
        parameters,
        str(path.parent),
        SW_SHOWNORMAL,
    )
    result_code = int(result or 0)
    if result_code <= 32:
        raise OSError(result_code, "Windows Explorer could not select the media file")
    return parameters


def clamp_trim_range(start_seconds, end_seconds, duration_seconds, minimum_duration=0.25):
    duration = max(float(duration_seconds or 0), 0.0)
    minimum = max(float(minimum_duration or 0), 0.01)
    start = max(0.0, min(float(start_seconds or 0), duration))
    end = max(0.0, min(float(end_seconds or 0), duration))
    if duration <= minimum:
        return 0.0, duration
    if end - start < minimum:
        if start + minimum <= duration:
            end = start + minimum
        else:
            end = duration
            start = max(0.0, end - minimum)
    return start, end


def format_precise_duration(seconds):
    total_milliseconds = max(0, int(round(float(seconds or 0) * 1000)))
    milliseconds = total_milliseconds % 1000
    total_seconds = total_milliseconds // 1000
    minutes, sec = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{sec:02d}.{milliseconds:03d}"


def trimmed_copy_path(path):
    path = Path(path)
    return unique_destination_path(path.with_name(f"{path.stem} - Trimmed{path.suffix}"))


def parse_audio_segment_times(path):
    match = re.match(r"(?:desktop|mic)_(\d+)_(\d+)\.wav$", path.name)
    if not match:
        return None
    return int(match.group(1)) / 1000.0, int(match.group(2)) / 1000.0


def parse_replay_segment_start(path):
    match = re.match(r"segment_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.mkv$", path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S").timestamp()
    except ValueError:
        return None


class Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", Rect),
        ("rcWork", Rect),
        ("dwFlags", wintypes.DWORD),
    ]


class MonitorInfoEx(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", Rect),
        ("rcWork", Rect),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * CCHDEVICENAME),
    ]


def enum_monitors():
    if os.name != "nt":
        return []

    monitors = []
    user32 = ctypes.windll.user32
    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(Rect),
        wintypes.LPARAM,
    )

    def callback(hmonitor, hdc, rect_ptr, lparam):
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rect = info.rcMonitor
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            monitors.append({
                "index": len(monitors),
                "left": int(rect.left),
                "top": int(rect.top),
                "width": int(width),
                "height": int(height),
                "primary": bool(info.dwFlags & 1),
            })
        return True

    user32.EnumDisplayMonitors(0, 0, monitor_enum_proc(callback), 0)
    return monitors


def monitor_label(monitor):
    primary = " primary" if monitor.get("primary") else ""
    return (
        f"Monitor {monitor['index'] + 1}: "
        f"{monitor['width']}x{monitor['height']} @ "
        f"{monitor['left']},{monitor['top']}{primary}"
    )


def enum_windows():
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    titles = []
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title and title not in titles:
            titles.append(title)
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return sorted(titles, key=str.casefold)


class Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", Point),
    ]


class KbdLlHookStruct(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class WndClassEx(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HANDLE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HANDLE),
    ]


class NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HANDLE),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", Guid),
        ("hBalloonIcon", wintypes.HANDLE),
    ]


class TrayIconThread(threading.Thread):
    def __init__(self, dispatch, log, state_getter=None):
        super().__init__(daemon=True)
        self.dispatch = dispatch
        self.log = log
        self.state_getter = state_getter
        self.ready = threading.Event()
        self.thread_id = None
        self.hwnd = None
        self.hicon = None
        self.hicon_from_file = False
        self.hinstance = None
        self.class_name = f"{APP_NAME}TrayWindow{int(time.time() * 1000)}"
        self.notify_queue = queue.Queue()
        self._wndproc_ref = None

    def run(self):
        if os.name != "nt":
            self.ready.set()
            return
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        kernel32.GetModuleHandleW.restype = wintypes.HANDLE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HANDLE,
            wintypes.LPVOID,
        ]
        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.TrackPopupMenu.restype = ctypes.c_int
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        self.thread_id = kernel32.GetCurrentThreadId()
        self.hinstance = kernel32.GetModuleHandleW(None)
        self.hicon = self.load_app_icon(user32)
        self._wndproc_ref = WNDPROC(self._wndproc)

        wndclass = WndClassEx()
        wndclass.cbSize = ctypes.sizeof(WndClassEx)
        wndclass.lpfnWndProc = self._wndproc_ref
        wndclass.hInstance = self.hinstance
        wndclass.hIcon = self.hicon
        wndclass.hIconSm = self.hicon
        wndclass.lpszClassName = self.class_name
        if not user32.RegisterClassExW(ctypes.byref(wndclass)):
            self.log("Tray icon could not register its window class.")
            self.ready.set()
            return

        self.hwnd = user32.CreateWindowExW(
            0,
            self.class_name,
            APP_NAME,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self.hinstance,
            None,
        )
        if not self.hwnd:
            self.log("Tray icon could not create its hidden window.")
            user32.UnregisterClassW(self.class_name, self.hinstance)
            self.ready.set()
            return

        if self._add_icon():
            self.log("Tray icon ready.")
        self.ready.set()

        msg = Msg()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._delete_icon()
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.hicon and self.hicon_from_file:
            try:
                user32.DestroyIcon(self.hicon)
            except Exception:
                pass
        user32.UnregisterClassW(self.class_name, self.hinstance)

    def load_app_icon(self, user32):
        icon_path = resource_path(APP_ICON_NAME)
        if icon_path.exists():
            try:
                hicon = user32.LoadImageW(
                    None,
                    str(icon_path),
                    IMAGE_ICON,
                    0,
                    0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE,
                )
                if hicon:
                    self.hicon_from_file = True
                    return hicon
            except Exception:
                pass
        self.hicon_from_file = False
        return user32.LoadIconW(None, IDI_APPLICATION)

    def _base_notify_data(self):
        data = NotifyIconData()
        data.cbSize = ctypes.sizeof(NotifyIconData)
        data.hWnd = self.hwnd
        data.uID = 1
        return data

    def _add_icon(self):
        data = self._base_notify_data()
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = self.hicon
        data.szTip = APP_NAME
        ok = ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))
        return bool(ok)

    def set_tooltip(self, text):
        if os.name != "nt" or not self.hwnd:
            return
        data = self._base_notify_data()
        data.uFlags = NIF_TIP
        data.szTip = str(text)[:127]
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def _delete_icon(self):
        if self.hwnd:
            data = self._base_notify_data()
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))

    def notify(self, title, message):
        if os.name != "nt":
            return
        self.notify_queue.put((str(title)[:63], str(message)[:255]))
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_TRAY_NOTIFY, 0, 0)

    def stop(self):
        if os.name == "nt" and self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def _show_next_notification(self):
        try:
            title, message = self.notify_queue.get_nowait()
        except queue.Empty:
            return
        data = self._base_notify_data()
        data.uFlags = NIF_INFO
        data.szInfoTitle = title
        data.szInfo = message
        data.dwInfoFlags = NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def _show_menu(self):
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            state = {}
            if self.state_getter:
                try:
                    state = self.state_getter()
                except Exception:
                    state = {}
            replay_label = "Stop Replay Buffer" if state.get("replay") else "Start Replay Buffer"
            recording_label = "Stop Full Recording" if state.get("recording") else "Start Full Recording"
            items = [
                (TRAY_OPEN, "Show ShadowClip"),
                (TRAY_HIDE, "Hide to Tray"),
                (0, None),
                (TRAY_TOGGLE_REPLAY, replay_label),
                (TRAY_SAVE_CLIP, "Save Clip"),
                (TRAY_TOGGLE_RECORDING, recording_label),
                (TRAY_STOP_ALL, "Stop All"),
                (TRAY_MAKE_BORDERLESS, "Minecraft Borderless Fix"),
                (TRAY_OPEN_OUTPUT, "Open Clips Folder"),
                (TRAY_OPEN_LAST_CLIP, "Open Last Clip"),
                (TRAY_SHOW_LAST_CLIP, "Show Last Clip in Explorer"),
                (0, None),
                (TRAY_EXIT, "Exit ShadowClip"),
            ]
            for command, label in items:
                if command:
                    user32.AppendMenuW(menu, MF_STRING, command, label)
                else:
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            point = Point()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(self.hwnd)
            command = user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                point.x,
                point.y,
                0,
                self.hwnd,
                None,
            )
            if command:
                action = {
                    TRAY_OPEN: "show_window",
                    TRAY_HIDE: "hide_window",
                    TRAY_TOGGLE_REPLAY: "toggle_replay",
                    TRAY_SAVE_CLIP: "save_clip",
                    TRAY_TOGGLE_RECORDING: "toggle_recording",
                    TRAY_STOP_ALL: "stop_all",
                    TRAY_MAKE_BORDERLESS: "make_borderless",
                    TRAY_OPEN_OUTPUT: "open_output",
                    TRAY_OPEN_LAST_CLIP: "open_last_clip",
                    TRAY_SHOW_LAST_CLIP: "show_last_clip",
                    TRAY_EXIT: "exit",
                }.get(command)
                if action:
                    self.dispatch(action)
        finally:
            user32.DestroyMenu(menu)

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == WM_TRAYICON:
            event = int(lparam) & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK, NIN_SELECT, NIN_KEYSELECT):
                self.dispatch("show_window")
                return 0
            if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_menu()
                return 0
        if message == WM_TRAY_NOTIFY:
            self._show_next_notification()
            return 0
        if message in (WM_CLOSE, WM_DESTROY):
            ctypes.windll.user32.PostQuitMessage(0)
            return 0
        return ctypes.windll.user32.DefWindowProcW(hwnd, message, wparam, lparam)


class HotkeyThread(threading.Thread):
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    def __init__(self, dispatch, log, hotkeys=None):
        super().__init__(daemon=True)
        self.dispatch = dispatch
        self.log = log
        self.thread_id = None
        self.ready = threading.Event()
        self.hook_bindings = {}
        self.keyboard_hook = None
        self.keyboard_proc = None
        self.last_dispatch_at = {}
        self.bindings = self.build_bindings(hotkeys or DEFAULT_CONFIG["hotkeys"])

    def build_bindings(self, hotkeys):
        bindings = {}
        used = {}
        self.hook_bindings = {}
        for hotkey_id, (action, label) in enumerate(HOTKEY_ACTIONS, start=1):
            raw = (hotkeys or {}).get(action, DEFAULT_CONFIG["hotkeys"][action])
            try:
                modifiers, key, normalized = parse_hotkey_text(raw)
            except ValueError as exc:
                fallback = DEFAULT_CONFIG["hotkeys"][action]
                self.log(f"Invalid hotkey for {label}: {exc}. Using {fallback}.")
                modifiers, key, normalized = parse_hotkey_text(fallback)
            signature = (modifiers, key)
            if signature in used:
                self.log(f"Hotkey duplicate skipped for {label}: {normalized} is already used by {used[signature]}.")
                continue
            used[signature] = label
            bindings[hotkey_id] = (label, modifiers, key, action, normalized)
            self.hook_bindings[signature] = (label, action, normalized)
        return bindings

    def current_modifier_state(self, user32):
        state = 0
        if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
            state |= MOD_ALT
        if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
            state |= MOD_CONTROL
        if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
            state |= MOD_SHIFT
        if (user32.GetAsyncKeyState(VK_LWIN) | user32.GetAsyncKeyState(VK_RWIN)) & 0x8000:
            state |= MOD_WIN
        return state

    def dispatch_once(self, action):
        now = time.monotonic()
        last = self.last_dispatch_at.get(action, 0)
        if now - last < 0.45:
            return
        self.last_dispatch_at[action] = now
        self.dispatch(action)

    def install_keyboard_hook(self, user32, kernel32):
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            LOWLEVELKEYBOARDPROC,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        def keyboard_proc(n_code, w_param, l_param):
            try:
                if n_code == HC_ACTION and int(w_param) in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    info = ctypes.cast(l_param, ctypes.POINTER(KbdLlHookStruct)).contents
                    key = int(info.vkCode)
                    modifiers = self.current_modifier_state(user32)
                    binding = self.hook_bindings.get((modifiers, key))
                    if binding:
                        self.dispatch_once(binding[1])
            except Exception:
                pass
            return user32.CallNextHookEx(self.keyboard_hook, n_code, w_param, l_param)

        self.keyboard_proc = LOWLEVELKEYBOARDPROC(keyboard_proc)
        module = kernel32.GetModuleHandleW(None)
        self.keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self.keyboard_proc, module, 0)
        if self.keyboard_hook:
            self.log("Low-level hotkey hook active.")
        else:
            self.log("Low-level hotkey hook could not be installed.")

    def run(self):
        if os.name != "nt":
            return
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        registered = []
        hook_only = []
        for hotkey_id, (name, modifiers, key, action, normalized) in self.bindings.items():
            if modifiers == 0:
                hook_only.append(normalized)
                continue
            ok = user32.RegisterHotKey(None, hotkey_id, modifiers, key)
            if ok:
                registered.append(hotkey_id)
            else:
                self.log(f"Hotkey not registered: {name} ({normalized})")
        if registered:
            summary = ", ".join(self.bindings[hotkey_id][4] for hotkey_id in registered if hotkey_id in self.bindings)
            self.log(f"Hotkeys registered: {summary}")
        if hook_only:
            self.log(f"Standalone hotkeys active through low-level hook: {', '.join(hook_only)}")
        self.install_keyboard_hook(user32, kernel32)
        self.ready.set()

        msg = Msg()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == self.WM_HOTKEY:
                binding = self.bindings.get(int(msg.wParam))
                if binding:
                    self.dispatch_once(binding[3])

        if self.keyboard_hook:
            user32.UnhookWindowsHookEx(self.keyboard_hook)
            self.keyboard_hook = None
        for hotkey_id in registered:
            user32.UnregisterHotKey(None, hotkey_id)

    def stop(self):
        if os.name == "nt" and self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)


class VirtualProcess:
    def __init__(self, label):
        self.label = label
        self.returncode = None
        self.stdin = None
        self._running = True

    def poll(self):
        return None if self._running else self.returncode

    def mark_stopped(self, returncode=0):
        self._running = False
        self.returncode = returncode

    def wait(self, timeout=None):
        if self._running:
            start = time.time()
            while self._running:
                if timeout is not None and time.time() - start >= timeout:
                    raise subprocess.TimeoutExpired(self.label, timeout)
                time.sleep(0.05)
        return self.returncode

    def terminate(self):
        self.mark_stopped(0)

    def kill(self):
        self.mark_stopped(1)


class ObsWebSocketClient:
    def __init__(self, host, port, password, timeout=15):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout
        self.sock = None
        self.request_lock = threading.RLock()

    def connect(self):
        deadline = time.time() + self.timeout
        last_error = None
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=2)
                break
            except OSError as exc:
                last_error = exc
                time.sleep(0.35)
        if not self.sock:
            raise RuntimeError(f"Could not connect to OBS websocket: {last_error}")

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: obswebsocket.json\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.recv_exact(1)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(response.decode("utf-8", errors="replace"))

        hello = self.recv_json()
        data = dict(hello.get("d") or {})
        identify = {
            "rpcVersion": min(int(data.get("rpcVersion", 1) or 1), 1),
            "eventSubscriptions": 0,
        }
        auth = data.get("authentication")
        if auth:
            identify["authentication"] = self.auth_string(auth["salt"], auth["challenge"])
        self.send_json({"op": 1, "d": identify})
        identified = self.recv_json()
        if identified.get("op") != 2:
            raise RuntimeError(f"OBS websocket identify failed: {identified}")
        return self

    def auth_string(self, salt, challenge):
        secret = base64.b64encode(hashlib.sha256((self.password + salt).encode("utf-8")).digest()).decode("ascii")
        return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")

    def recv_exact(self, count):
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise RuntimeError("OBS websocket connection closed")
            data += chunk
        return data

    def recv_json(self):
        while True:
            first, second = self.recv_exact(2)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self.recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self.recv_exact(8))[0]
            mask = self.recv_exact(4) if masked else b""
            payload = self.recv_exact(length)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 8:
                raise RuntimeError("OBS websocket closed by peer")
            if opcode == 1:
                return json.loads(payload.decode("utf-8"))

    def send_json(self, message):
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = bytearray([0x81])
        if len(payload) < 126:
            header.append(0x80 | len(payload))
        elif len(payload) <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", len(payload)))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", len(payload)))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def request(self, request_type, request_data=None):
        with self.request_lock:
            request_id = str(uuid.uuid4())
            self.send_json({
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": request_id,
                    "requestData": request_data or {},
                },
            })
            while True:
                message = self.recv_json()
                data = message.get("d") or {}
                if message.get("op") == 7 and data.get("requestId") == request_id:
                    status = data.get("requestStatus") or {}
                    if not status.get("result"):
                        raise RuntimeError(f"{request_type} failed: {status}")
                    return data.get("responseData") or {}

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None


class FfmpegManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.record_proc = None
        self.record_log_handle = None
        self.recording_active_backend = None
        self.replay_proc = None
        self.replay_log_handle = None
        self.replay_should_restart = False
        self.replay_watchdog_thread = None
        self.replay_backend_override = None
        self.replay_active_backend = None
        self.replay_restart_count = 0
        self.replay_current_log_path = None
        self.replay_dir = self.runtime_dir / "buffer"
        self.obs_proc = None
        self.obs_client = None
        self.obs_runtime_lock = threading.RLock()
        self.obs_process_started_at = 0.0
        self.obs_frontend_ready = False
        self.obs_scene_name = "ShadowClip"
        self.obs_display_input_name = "ShadowClip Display Fallback"
        self.obs_game_input_name = "ShadowClip Game Capture"
        self.obs_scene_capture_mode = None
        self.obs_display_monitor_id = None
        self.obs_display_settings_signature = None
        self.obs_scene_transform_signatures = {}
        self.obs_game_settings_signature = None
        self.obs_replay_resetting = False
        self.obs_replay_watchdog_grace_until = 0.0
        self.obs_canvas_mismatch_since = 0.0
        self.obs_canvas_restart_at = 0.0
        self.obs_capture_context_key = ""
        self.obs_capture_strategy = "auto"
        self.obs_capture_strategy_cache = {}
        self.obs_capture_strategy_changed_at = 0.0
        self.obs_capture_last_probe_at = 0.0
        self.obs_capture_black_samples = 0
        self.obs_capture_good_samples = 0
        self.obs_capture_recovery_pending_reset = False
        self.obs_capture_unresolved_logged = False
        self.obs_record_watchdog_thread = None
        self.last_game_capture_label = ""
        self.last_game_capture_label_at = 0.0
        self.stop_cleanup = threading.Event()
        self.cleanup_thread = None
        self.encoder_cache = None
        self.encoder_log_signature = None
        self.ffmpeg_encoder_names_cache = None
        self.gpu_adapter_names_cache = None
        self.ddagrab_cache = None
        self.save_lock = threading.Lock()
        self.storage_cleanup_lock = threading.Lock()
        self.storage_cleanup_running = False
        self.last_storage_cleanup_at = 0.0
        self.last_clip_saved_at = 0.0
        self.last_clip_path = None
        self.recording_started_at = None
        self.current_recording_path = None
        self.recording_uses_separate_audio = False
        self.recording_audio_owned = False
        self.warning_keys = set()
        self.audio_stop = threading.Event()
        self.audio_threads = {}
        self.audio_base_dir = self.runtime_dir / "audio"

    @property
    def runtime_dir(self):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = APP_DIR
        path = base / APP_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def logs_dir(self):
        path = self.runtime_dir / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def update_config(self, config):
        old_config = getattr(self, "config", {})
        if (
            old_config.get("video_encoder") != config.get("video_encoder")
            or old_config.get("ffmpeg_path") != config.get("ffmpeg_path")
        ):
            self.encoder_cache = None
            self.encoder_log_signature = None
            self.ffmpeg_encoder_names_cache = None
        if bool(old_config.get("capture_desktop_overlays", DEFAULT_CONFIG["capture_desktop_overlays"])) != bool(
            config.get("capture_desktop_overlays", DEFAULT_CONFIG["capture_desktop_overlays"])
        ):
            self.obs_capture_context_key = ""
            self.obs_capture_strategy = "auto"
            self.obs_capture_strategy_cache.clear()
            self.obs_scene_capture_mode = None
            self.obs_display_settings_signature = None
        self.config = config

    def remember_capture_label(self, label):
        cleaned = friendly_application_name(label, "", label)
        ignored = {
            "",
            "desktop",
            APP_NAME.casefold(),
            Path(sys.executable).stem.casefold(),
            "applicationframehost",
            "explorer",
            "shellexperiencehost",
            "searchhost",
            "startmenuexperiencehost",
            "steamwebhelper",
            "textinputhost",
        }
        if cleaned.casefold() in ignored:
            return ""
        self.last_game_capture_label = cleaned
        self.last_game_capture_label_at = time.time()
        return cleaned

    def remember_capture_context(self, context):
        if not isinstance(context, dict):
            return ""
        process_name = str(context.get("process") or "").strip()
        title = str(context.get("title") or "").strip()
        return self.remember_capture_label(friendly_application_name(process_name, title, process_name or title))

    def cached_game_capture_label(self, max_age_seconds=6 * 60 * 60):
        if not self.last_game_capture_label:
            return ""
        if time.time() - self.last_game_capture_label_at > max_age_seconds:
            return ""
        return self.last_game_capture_label

    def find_ffmpeg(self):
        configured = str(self.config.get("ffmpeg_path", "")).strip()
        candidates = []
        if configured:
            candidates.append(expand_path(configured))
        candidates.extend([
            APP_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
            APP_DIR / "tools" / "ffmpeg" / "ffmpeg.exe",
            APP_DIR / "ffmpeg.exe",
        ])
        path_ffmpeg = shutil.which("ffmpeg")
        if path_ffmpeg:
            candidates.append(Path(path_ffmpeg))
        for candidate in candidates:
            if candidate and candidate.exists():
                return str(candidate)
        return ""

    def require_ffmpeg(self):
        ffmpeg = self.find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("FFmpeg not found. Run Install-FFmpeg.ps1 or set ffmpeg_path.")
        return ffmpeg

    def find_ffprobe(self):
        ffmpeg = self.find_ffmpeg()
        candidates = []
        if ffmpeg:
            candidates.append(Path(ffmpeg).with_name("ffprobe.exe"))
        path_ffprobe = shutil.which("ffprobe")
        if path_ffprobe:
            candidates.append(Path(path_ffprobe))
        for candidate in candidates:
            if candidate and candidate.exists():
                return str(candidate)
        return ""

    def find_obs_exe(self):
        configured = str(self.config.get("obs_path", "")).strip()
        candidates = []
        if configured:
            candidates.append(expand_path(configured))
        candidates.extend([
            APP_DIR / "tools" / "obs" / "bin" / "64bit" / "obs64.exe",
            APP_DIR / "tools" / "obs" / "obs64.exe",
            APP_DIR / "obs64.exe",
            APP_DIR.parent / "obs-runtime" / "bin" / "64bit" / "obs64.exe",
        ])
        path_obs = shutil.which("obs64")
        if path_obs:
            candidates.append(Path(path_obs))
        for candidate in candidates:
            if candidate and candidate.exists():
                return str(candidate)
        return ""

    def require_obs(self):
        obs = self.find_obs_exe()
        if not obs:
            raise RuntimeError(
                "OBS runtime not found. Put the portable OBS build in tools\\obs or set obs_path."
            )
        return obs

    def obs_root_dir(self, obs_exe):
        path = Path(obs_exe).resolve()
        if path.parent.name.casefold() == "64bit" and path.parent.parent.name.casefold() == "bin":
            return path.parent.parent.parent
        return path.parent

    def obs_websocket_port(self):
        try:
            return int(self.config.get("obs_websocket_port", 4457) or 4457)
        except (TypeError, ValueError):
            return 4457

    def obs_websocket_password(self):
        password = str(self.config.get("obs_websocket_password", "")).strip()
        return password or "ShadowClipLocal123"

    def write_obs_websocket_config(self, obs_root):
        config_dir = obs_root / "config" / "obs-studio" / "plugin_config" / "obs-websocket"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.json"
        data = {
            "alerts_enabled": False,
            "auth_required": True,
            "first_load": False,
            "server_enabled": True,
            "server_password": self.obs_websocket_password(),
            "server_port": self.obs_websocket_port(),
        }
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    def obs_client_connect(self, timeout=15):
        client = ObsWebSocketClient(
            "127.0.0.1",
            self.obs_websocket_port(),
            self.obs_websocket_password(),
            timeout=timeout,
        ).connect()
        return client

    def wait_for_obs_frontend_ready(self, client, settle_seconds=8.0, timeout=20.0):
        if self.obs_frontend_ready:
            return

        process_age = time.monotonic() - self.obs_process_started_at if self.obs_process_started_at else settle_seconds
        wait_seconds = max(0.0, settle_seconds - process_age)
        if wait_seconds > 0:
            self.log(
                f"OBS cold-start guard: waiting {wait_seconds:.1f}s for frontend/video initialization."
            )
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                if self.obs_proc and self.obs_proc.poll() is not None:
                    raise RuntimeError(
                        f"OBS exited during cold-start guard (code {self.obs_proc.returncode})."
                    )
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

        deadline = time.monotonic() + timeout
        last_error = None
        stable_samples = 0
        while time.monotonic() < deadline:
            if self.obs_proc and self.obs_proc.poll() is not None:
                raise RuntimeError(
                    f"OBS exited before frontend initialization completed (code {self.obs_proc.returncode})."
                )
            try:
                client.request("GetVersion")
                video = client.request("GetVideoSettings")
                scenes = client.request("GetSceneList")
                dimensions = (
                    int(video.get("baseWidth") or 0),
                    int(video.get("baseHeight") or 0),
                    int(video.get("outputWidth") or 0),
                    int(video.get("outputHeight") or 0),
                    int(video.get("fpsNumerator") or 0),
                    int(video.get("fpsDenominator") or 0),
                )
                if all(value > 0 for value in dimensions) and isinstance(scenes.get("scenes"), list):
                    stable_samples += 1
                    if stable_samples >= 2:
                        self.obs_frontend_ready = True
                        self.log("OBS frontend/video initialization is stable.")
                        return
                else:
                    stable_samples = 0
                    last_error = RuntimeError(f"incomplete OBS video settings: {dimensions}")
            except Exception as exc:
                stable_samples = 0
                last_error = exc
            time.sleep(0.65)
        raise RuntimeError(f"OBS frontend/video initialization did not stabilize: {last_error}")

    def ensure_obs_runtime(self):
        with self.obs_runtime_lock:
            for attempt in range(2):
                try:
                    return self._ensure_obs_runtime_locked()
                except Exception as exc:
                    retryable_cold_start = not self.obs_frontend_ready
                    if attempt or not retryable_cold_start:
                        raise
                    self.log(
                        f"OBS cold start failed before frontend readiness: {exc}. "
                        "Restarting the private OBS runtime once."
                    )
                    self._stop_obs_runtime_locked()
                    time.sleep(2.5)
            raise RuntimeError("OBS runtime could not be initialized.")

    def _ensure_obs_runtime_locked(self):
        if self.obs_client:
            try:
                self.obs_client.request("GetVersion")
                self.wait_for_obs_frontend_ready(self.obs_client)
                return self.obs_client
            except Exception:
                try:
                    self.obs_client.close()
                except Exception:
                    pass
                self.obs_client = None

        obs_exe = self.require_obs()
        obs_root = self.obs_root_dir(obs_exe)
        self.write_obs_websocket_config(obs_root)
        if not self.obs_proc or self.obs_proc.poll() is not None:
            self.obs_frontend_ready = False
            args = [
                obs_exe,
                "--portable",
                "--multi",
                "--disable-updater",
                "--disable-missing-files-check",
                "--minimize-to-tray",
                "--only-bundled-plugins",
                "--profile", "ShadowClip",
                "--collection", "ShadowClip",
                "--websocket_port", str(self.obs_websocket_port()),
                "--websocket_password", self.obs_websocket_password(),
                "--websocket_ipv4_only",
            ]
            self.obs_proc = subprocess.Popen(
                args,
                cwd=str(Path(obs_exe).parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            self.obs_process_started_at = time.monotonic()
        self.obs_client = self.obs_client_connect(timeout=20)
        self.wait_for_obs_frontend_ready(self.obs_client)
        deadline = time.time() + 20.0
        last_error = None
        version = None
        while time.time() < deadline:
            try:
                version = self.obs_client.request("GetVersion")
                break
            except Exception as exc:
                last_error = exc
                if "not ready" not in str(exc).casefold():
                    raise
                time.sleep(0.5)
        if version is None:
            raise RuntimeError(f"OBS did not become ready: {last_error}")
        self.log(
            f"OBS runtime ready: OBS {version.get('obsVersion', '?')}, "
            f"obs-websocket {version.get('obsWebSocketVersion', '?')}."
        )
        return self.obs_client

    def obs_output_dir(self):
        path = self.capture_output_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def obs_video_size(self):
        monitors = enum_monitors()
        if monitors:
            index = int(self.config.get("monitor_index", 0) or 0)
            index = max(0, min(index, len(monitors) - 1))
            monitor = monitors[index]
            return int(monitor["width"]), int(monitor["height"])
        return 1920, 1080

    def obs_ini_path(self, path):
        return str(Path(path)).replace("\\", "\\\\")

    def obs_replay_buffer_mb(self):
        if bool(self.config.get("obs_replay_ram_auto", DEFAULT_CONFIG["obs_replay_ram_auto"])):
            value = recommended_obs_replay_buffer_mb(
                self.config.get("clip_seconds", DEFAULT_CONFIG["clip_seconds"]),
                self.config.get("video_bitrate_mbps", DEFAULT_CONFIG["video_bitrate_mbps"]),
            )
            self.config["obs_replay_buffer_mb"] = value
            return value
        try:
            value = int(self.config.get("obs_replay_buffer_mb", DEFAULT_CONFIG["obs_replay_buffer_mb"]) or DEFAULT_CONFIG["obs_replay_buffer_mb"])
        except (TypeError, ValueError):
            value = DEFAULT_CONFIG["obs_replay_buffer_mb"]
        return max(64, min(2048, value))

    def obs_estimated_clip_mb(self):
        try:
            bitrate = max(1, int(self.config.get("video_bitrate_mbps", 35) or 35))
            seconds = max(1, int(self.config.get("clip_seconds", 30) or 30))
        except (TypeError, ValueError):
            return 0
        return int((bitrate * seconds) / 8)

    def write_obs_capture_profile_config(self, obs_root):
        width, height = self.obs_video_size()
        fps = max(1, int(self.config.get("framerate", 60) or 60))
        output_dir = self.obs_output_dir()
        container = str(self.config.get("container", "mp4")).casefold()
        obs_format = "hybrid_mp4" if container == "mp4" else "mkv"
        bitrate = max(1000, int(self.config.get("video_bitrate_mbps", 35) or 35) * 1000)
        clip_seconds = max(1, int(self.config.get("clip_seconds", 30) or 30))
        replay_buffer_mb = self.obs_replay_buffer_mb()
        encoder = self.resolve_video_encoder(ffmpeg_limited=False, log_selection=True)
        simple_encoder = OBS_SIMPLE_ENCODERS.get(encoder, "x264")
        profile_dir = obs_root / "config" / "obs-studio" / "basic" / "profiles" / "ShadowClip"
        profile_dir.mkdir(parents=True, exist_ok=True)
        global_ini = obs_root / "config" / "obs-studio" / "global.ini"
        global_ini.parent.mkdir(parents=True, exist_ok=True)
        global_ini.write_text(
            "[Basic]\n"
            "Profile=ShadowClip\n"
            "ProfileDir=ShadowClip\n"
            "SceneCollection=ShadowClip\n"
            "SceneCollectionFile=ShadowClip\n",
            encoding="utf-8",
        )
        profile_text = f"""[General]
Name=ShadowClip

[Output]
Mode=Simple
FilenameFormatting=%CCYY-%MM-%DD_%hh-%mm-%ss
DelayEnable=false
DelaySec=20
DelayPreserve=true
Reconnect=true
RetryDelay=2
MaxRetries=25
BindIP=default
IPFamily=IPv4+IPv6
NewSocketLoopEnable=false
LowLatencyEnable=false

[SimpleOutput]
FilePath={self.obs_ini_path(output_dir)}
RecFormat2={obs_format}
VBitrate={bitrate}
ABitrate=160
UseAdvanced=false
Preset=veryfast
NVENCPreset2=p5
RecQuality=Small
RecRB=true
RecRBTime={clip_seconds}
RecRBSize={replay_buffer_mb}
RecRBPrefix=Replay
StreamAudioEncoder=aac
RecAudioEncoder=aac
RecTracks=1
StreamEncoder={simple_encoder}
RecEncoder={simple_encoder}

[AdvOut]
ApplyServiceSettings=true
UseRescale=false
TrackIndex=1
VodTrackIndex=2
Encoder=obs_x264
RecType=Standard
RecFilePath={self.obs_ini_path(output_dir)}
RecFormat2={obs_format}
RecUseRescale=false
RecTracks=1
RecEncoder=none
FLVTrack=1
StreamMultiTrackAudioMixes=1
FFOutputToFile=true
FFFilePath={self.obs_ini_path(output_dir)}
FFExtension={container}
FFVBitrate={bitrate}
FFVGOPSize=250
FFUseRescale=false
FFIgnoreCompat=false
FFABitrate=160
FFAudioMixes=1
Track1Bitrate=160
Track2Bitrate=160
Track3Bitrate=160
Track4Bitrate=160
Track5Bitrate=160
Track6Bitrate=160
RecSplitFileTime=15
RecSplitFileSize=2048
RecRB=true
RecRBTime={clip_seconds}
RecRBSize={replay_buffer_mb}
AudioEncoder=ffmpeg_aac
RecAudioEncoder=ffmpeg_aac

[Video]
BaseCX={width}
BaseCY={height}
OutputCX={width}
OutputCY={height}
FPSType=2
FPSCommon={fps}
FPSInt={fps}
FPSNum={fps}
FPSDen=1
ScaleType=bicubic
ColorFormat=NV12
ColorSpace=709
ColorRange=Partial
SdrWhiteLevel=300
HdrNominalPeakLevel=1000

[Audio]
MonitoringDeviceId=default
MonitoringDeviceName=Default
SampleRate=48000
ChannelSetup=Stereo
MeterDecayRate=23.53
PeakMeterType=0
"""
        (profile_dir / "basic.ini").write_text(profile_text, encoding="utf-8")

    def obs_output_active(self, client):
        for request_type in ("GetReplayBufferStatus", "GetRecordStatus"):
            try:
                if client.request(request_type).get("outputActive"):
                    return True
            except Exception:
                pass
        return False

    def obs_replay_buffer_active(self, client):
        try:
            return bool(client.request("GetReplayBufferStatus").get("outputActive"))
        except Exception:
            return False

    def obs_recording_active(self, client):
        try:
            return bool(client.request("GetRecordStatus").get("outputActive"))
        except Exception:
            return False

    def set_obs_video_settings_for_size(self, client, width, height):
        fps = max(1, int(self.config.get("framerate", 60) or 60))
        client.request("SetVideoSettings", {
            "baseWidth": int(width),
            "baseHeight": int(height),
            "outputWidth": int(width),
            "outputHeight": int(height),
            "fpsNumerator": fps,
            "fpsDenominator": 1,
        })

    def wait_for_obs_replay_buffer_inactive(self, client, timeout=4.0):
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            try:
                status = client.request("GetReplayBufferStatus")
                if not status.get("outputActive"):
                    return True
            except Exception:
                return False
            time.sleep(0.15)
        return not self.obs_replay_buffer_active(client)

    def wait_for_obs_replay_buffer_active(self, client, timeout=5.0):
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            try:
                status = client.request("GetReplayBufferStatus")
                if status.get("outputActive"):
                    return True
            except Exception:
                return False
            time.sleep(0.15)
        return self.obs_replay_buffer_active(client)

    def ensure_obs_canvas_matches_monitor(self, client):
        desired_width, desired_height = self.obs_video_size()
        current_width, current_height = self.obs_live_canvas_size(client)
        if (int(current_width), int(current_height)) == (int(desired_width), int(desired_height)):
            self.obs_canvas_mismatch_since = 0.0
            return False

        now = time.time()
        if not self.obs_canvas_mismatch_since:
            self.obs_canvas_mismatch_since = now
            self.log(
                f"OBS canvas mismatch detected: OBS is {current_width}x{current_height}, "
                f"selected monitor is {desired_width}x{desired_height}."
            )
            return False
        if now - self.obs_canvas_mismatch_since < 3.0:
            return False
        if now - self.obs_canvas_restart_at < 12.0:
            return False
        if self.obs_replay_resetting:
            return False
        if self.obs_recording_active(client):
            self.warn_once(
                "obs_canvas_mismatch_recording",
                "OBS canvas no longer matches the selected monitor, but recording is active; keeping current size until recording stops.",
            )
            return False

        replay_was_active = self.obs_replay_buffer_active(client)
        self.obs_replay_resetting = True
        try:
            if replay_was_active:
                client.request("StopReplayBuffer")
                self.wait_for_obs_replay_buffer_inactive(client)
            self.set_obs_video_settings_for_size(client, desired_width, desired_height)
            self.set_obs_scene_item_full_canvas_transform(client, self.obs_display_input_name, force=True)
            self.set_obs_scene_item_full_canvas_transform(client, self.obs_game_input_name, force=True)
            self.update_obs_scene_capture_selection(client, force=True)
            if replay_was_active:
                self.start_obs_replay_buffer_with_retry(client)
                self.obs_replay_watchdog_grace_until = time.time() + 5.0
            self.obs_canvas_restart_at = now
            self.obs_canvas_mismatch_since = 0.0
            self.log(
                f"OBS canvas updated: {current_width}x{current_height} -> "
                f"{desired_width}x{desired_height}; replay buffer restarted."
            )
            return True
        finally:
            self.obs_replay_resetting = False

    def obs_monitor_id_for_context(self, context=None):
        if str(self.config.get("capture_mode", "")) == "monitor":
            monitor_id = monitor_device_name_for_index(int(self.config.get("monitor_index", 0) or 0))
            if monitor_id:
                return monitor_id
        if isinstance(context, dict):
            monitor_id = monitor_device_name_from_window(context.get("hwnd"))
            if monitor_id:
                return monitor_id
        context = foreground_window_basic_context()
        if context:
            monitor_id = monitor_device_name_from_window(context.get("hwnd"))
            if monitor_id:
                return monitor_id
        return monitor_device_name_for_index(0)

    def obs_display_input_settings(self, context=None, method=None):
        if method is None:
            method = 2 if self.obs_capture_strategy in {"display_wgc", "game_window_wgc", "overlay_wgc"} else 0
        settings = {
            "capture_cursor": True,
            "method": int(method),
            "force_sdr": False,
        }
        monitor_id = self.obs_monitor_id_for_context(context)
        if monitor_id:
            settings["monitor_id"] = monitor_id
        return settings

    def update_obs_display_input_settings(self, client, context=None, force=False):
        settings = self.obs_display_input_settings(context)
        monitor_id = str(settings.get("monitor_id") or "")
        signature = json.dumps(settings, sort_keys=True, ensure_ascii=False)
        # Reapplying identical live WGC settings can race win-capture's render
        # thread. The local signature is authoritative because ShadowClip owns
        # this private OBS scene.
        if signature == self.obs_display_settings_signature:
            return
        try:
            client.request("SetInputSettings", {
                "inputName": self.obs_display_input_name,
                "inputSettings": settings,
                "overlay": True,
            })
            if monitor_id:
                self.obs_display_monitor_id = monitor_id
            self.obs_display_settings_signature = signature
        except Exception as exc:
            self.warn_once("obs_monitor_fallback_update", f"OBS monitor fallback update failed: {exc}")

    def obs_minecraft_capture_mode(self):
        value = str(self.config.get("obs_minecraft_capture_mode", "specific_game") or "specific_game").casefold()
        if value not in {"specific_game", "display", "any_fullscreen"}:
            value = "specific_game"
        return value

    def obs_window_selector_from_context(self, context):
        if not isinstance(context, dict):
            return ""
        title = str(context.get("title") or "").strip() or "Minecraft"
        class_name = str(context.get("class") or "").strip()
        exe_name = str(context.get("exe") or "").strip()
        if not exe_name:
            process_name = str(context.get("process") or "").strip()
            exe_name = process_name if process_name.casefold().endswith(".exe") else f"{process_name}.exe"
        exe_name = exe_name.strip()
        if not exe_name or exe_name == ".exe":
            return ""
        return f"{title}:{class_name}:{exe_name}"

    def obs_capture_identity(self, context):
        process_name = process_name_key(context.get("process")) if isinstance(context, dict) else ""
        monitor_id = self.obs_monitor_id_for_context(context) or "primary"
        if not process_name:
            process_name = "desktop"
        return f"{process_name}|{monitor_id.casefold()}"

    def prepare_obs_capture_context(self, context):
        identity = self.obs_capture_identity(context)
        if identity == self.obs_capture_context_key:
            return identity
        self.obs_capture_context_key = identity
        minecraft_safe = is_opengl_game_context(context) and self.obs_minecraft_capture_mode() == "specific_game"
        if minecraft_safe:
            # OBS 32.1.2 can crash in win-capture when a WGC monitor source and
            # Minecraft's reconnecting OpenGL hook are probed together.
            self.obs_capture_strategy = "game_only"
        else:
            default_strategy = (
                "overlay_wgc"
                if bool(self.config.get("capture_desktop_overlays", DEFAULT_CONFIG["capture_desktop_overlays"]))
                else "auto"
            )
            self.obs_capture_strategy = self.obs_capture_strategy_cache.get(identity, default_strategy)
        self.obs_capture_strategy_changed_at = time.time()
        self.obs_capture_last_probe_at = 0.0
        self.obs_capture_black_samples = 0
        self.obs_capture_good_samples = 0
        self.obs_capture_recovery_pending_reset = False
        self.obs_capture_unresolved_logged = False
        self.obs_scene_capture_mode = None
        return identity

    def obs_strategy_uses_game_capture(self, base_mode):
        if base_mode not in {"game_capture", "minecraft_game_capture"}:
            return False
        return self.obs_capture_strategy not in {"display_auto", "display_wgc"}

    def obs_strategy_uses_specific_window(self, base_mode):
        return base_mode == "minecraft_game_capture" or self.obs_capture_strategy == "game_window_wgc"

    def obs_game_input_settings(self, context=None, minecraft_specific=False):
        settings = {
            "capture_cursor": True,
            "capture_overlays": True,
            "anti_cheat_hook": True,
            "hook_rate": 2,
        }
        if minecraft_specific:
            selector = self.obs_window_selector_from_context(context)
            if selector:
                settings.update({
                    "capture_mode": "window",
                    "window": selector,
                    "priority": 2,
                    "sli_compatibility": True,
                })
                return settings
        settings.update({
            "capture_mode": "any_fullscreen",
            "priority": 2,
            "sli_compatibility": False,
        })
        return settings

    def update_obs_game_input_settings(self, client, context=None, minecraft_specific=False, force=False):
        settings = self.obs_game_input_settings(context=context, minecraft_specific=minecraft_specific)
        signature = json.dumps(settings, sort_keys=True, ensure_ascii=False)
        if signature == self.obs_game_settings_signature:
            return
        client.request("SetInputSettings", {
            "inputName": self.obs_game_input_name,
            "inputSettings": settings,
            "overlay": True,
        })
        self.obs_game_settings_signature = signature

    def obs_capture_source_mode(self):
        context = foreground_window_basic_context()
        if context and is_browser_process(context.get("process")):
            self.remember_capture_context(context)
            return "browser_display", context
        if context:
            self.remember_capture_context(context)
            process_key = process_name_key(context.get("process"))
            if process_key in DESKTOP_CAPTURE_PROCESSES:
                return "desktop_display", context
            if is_opengl_game_context(context):
                minecraft_mode = self.obs_minecraft_capture_mode()
                if minecraft_mode == "display":
                    return "minecraft_display", context
                if minecraft_mode == "specific_game":
                    return "minecraft_game_capture", context
                return "game_capture", context
            if bool(context.get("fullscreen")):
                return "game_capture", context
        return "desktop_display", context

    def obs_scene_item_id(self, client, source_name):
        try:
            items = client.request("GetSceneItemList", {"sceneName": self.obs_scene_name}).get("sceneItems", [])
            for item in items:
                if item.get("sourceName") == source_name:
                    return int(item.get("sceneItemId"))
        except Exception as exc:
            self.warn_once(f"obs_scene_item_{source_name}", f"OBS scene item lookup failed for {source_name}: {exc}")
        return None

    def set_obs_scene_item_enabled(self, client, source_name, enabled):
        item_id = self.obs_scene_item_id(client, source_name)
        if item_id is None:
            return False
        client.request("SetSceneItemEnabled", {
            "sceneName": self.obs_scene_name,
            "sceneItemId": item_id,
            "sceneItemEnabled": bool(enabled),
        })
        return True

    def set_obs_scene_item_index(self, client, source_name, index):
        item_id = self.obs_scene_item_id(client, source_name)
        if item_id is None:
            return False
        client.request("SetSceneItemIndex", {
            "sceneName": self.obs_scene_name,
            "sceneItemId": item_id,
            "sceneItemIndex": int(index),
        })
        return True

    def obs_live_canvas_size(self, client):
        try:
            settings = client.request("GetVideoSettings")
            width = int(settings.get("baseWidth") or settings.get("outputWidth") or 0)
            height = int(settings.get("baseHeight") or settings.get("outputHeight") or 0)
            if width > 0 and height > 0:
                return width, height
        except Exception:
            pass
        return self.obs_video_size()

    def obs_full_canvas_transform(self, client=None):
        width, height = self.obs_live_canvas_size(client) if client is not None else self.obs_video_size()
        return {
            "alignment": 5,
            "boundsAlignment": 5,
            "boundsType": "OBS_BOUNDS_STRETCH",
            "boundsWidth": float(width),
            "boundsHeight": float(height),
            "cropBottom": 0,
            "cropLeft": 0,
            "cropRight": 0,
            "cropTop": 0,
            "positionX": 0.0,
            "positionY": 0.0,
            "rotation": 0.0,
            "scaleX": 1.0,
            "scaleY": 1.0,
        }

    def obs_scene_item_transform(self, client, item_id):
        try:
            return client.request("GetSceneItemTransform", {
                "sceneName": self.obs_scene_name,
                "sceneItemId": item_id,
            }).get("sceneItemTransform", {})
        except Exception:
            return {}

    def obs_transform_matches_full_canvas(self, transform, expected):
        if not isinstance(transform, dict):
            return False

        def number(name, default=0.0):
            try:
                return float(transform.get(name, default) or default)
            except (TypeError, ValueError):
                return float(default)

        expected_width = float(expected["boundsWidth"])
        expected_height = float(expected["boundsHeight"])
        if str(transform.get("boundsType") or "") != expected["boundsType"]:
            return False
        if abs(number("boundsWidth") - expected_width) > 0.75:
            return False
        if abs(number("boundsHeight") - expected_height) > 0.75:
            return False
        if abs(number("positionX") - float(expected["positionX"])) > 0.75:
            return False
        if abs(number("positionY") - float(expected["positionY"])) > 0.75:
            return False
        for crop_name in ("cropBottom", "cropLeft", "cropRight", "cropTop"):
            if abs(number(crop_name) - float(expected[crop_name])) > 0.75:
                return False
        return True

    def set_obs_scene_item_full_canvas_transform(self, client, source_name, force=False):
        item_id = self.obs_scene_item_id(client, source_name)
        if item_id is None:
            return False
        transform = self.obs_full_canvas_transform(client)
        signature = (
            source_name,
            int(transform["boundsWidth"]),
            int(transform["boundsHeight"]),
            transform["boundsType"],
        )
        current = self.obs_scene_item_transform(client, item_id) if not force else {}
        if not force and self.obs_transform_matches_full_canvas(current, transform):
            self.obs_scene_transform_signatures[source_name] = signature
            return True
        client.request("SetSceneItemTransform", {
            "sceneName": self.obs_scene_name,
            "sceneItemId": item_id,
            "sceneItemTransform": transform,
        })
        self.obs_scene_transform_signatures[source_name] = signature
        if not force and current:
            try:
                old_width = float(current.get("boundsWidth") or 0)
                old_height = float(current.get("boundsHeight") or 0)
                self.log(
                    f"OBS source scaling repaired for {source_name}: "
                    f"{old_width:.0f}x{old_height:.0f} -> {int(transform['boundsWidth'])}x{int(transform['boundsHeight'])}."
                )
            except Exception:
                pass
        return True

    def update_obs_scene_capture_selection(self, client, force=False):
        base_mode, context = self.obs_capture_source_mode()
        self.prepare_obs_capture_context(context)
        use_game_capture = self.obs_strategy_uses_game_capture(base_mode)
        specific_window = self.obs_strategy_uses_specific_window(base_mode)
        display_method = 2 if self.obs_capture_strategy in {"display_wgc", "game_window_wgc", "overlay_wgc"} else 0
        display_enabled = self.obs_capture_strategy != "game_only"
        overlay_primary = self.obs_capture_strategy == "overlay_wgc" and use_game_capture
        mode = f"{base_mode}:{self.obs_capture_strategy}"
        if not force and mode == self.obs_scene_capture_mode:
            try:
                if display_enabled:
                    self.update_obs_display_input_settings(client, context=context)
                if use_game_capture:
                    self.update_obs_game_input_settings(client, context=context, minecraft_specific=specific_window)
                if display_enabled:
                    self.set_obs_scene_item_full_canvas_transform(client, self.obs_display_input_name)
                if use_game_capture:
                    self.set_obs_scene_item_full_canvas_transform(client, self.obs_game_input_name)
            except Exception as exc:
                self.warn_once(f"obs_scene_capture_refresh_{mode}", f"OBS capture source refresh failed: {exc}")
            return

        try:
            if display_enabled:
                self.update_obs_display_input_settings(client, context=context, force=True)
            if use_game_capture:
                self.update_obs_game_input_settings(
                    client,
                    context=context,
                    minecraft_specific=specific_window,
                    force=True,
                )
            # The monitor source stays live underneath Game Capture. Failed hooks are
            # transparent in OBS, so the display source can immediately fill the scene.
            self.set_obs_scene_item_enabled(client, self.obs_display_input_name, display_enabled)
            self.set_obs_scene_item_enabled(client, self.obs_game_input_name, use_game_capture)
            self.set_obs_scene_item_index(client, self.obs_game_input_name, 0 if overlay_primary else 1)
            self.set_obs_scene_item_index(client, self.obs_display_input_name, 1 if overlay_primary else 0)
            if display_enabled:
                self.set_obs_scene_item_full_canvas_transform(client, self.obs_display_input_name, force=force)
            if use_game_capture:
                self.set_obs_scene_item_full_canvas_transform(client, self.obs_game_input_name, force=force)
            previous = self.obs_scene_capture_mode
            self.obs_scene_capture_mode = mode
            if previous != mode:
                label = "desktop"
                if isinstance(context, dict):
                    label = context.get("process") or context.get("title") or "desktop"
                method_label = "WGC" if display_method == 2 else "Auto/DXGI"
                if overlay_primary:
                    self.log(f"OBS capture mode: WGC desktop overlays above game capture for {label}.")
                elif self.obs_capture_strategy == "game_only" and base_mode == "minecraft_game_capture":
                    self.log(f"OBS Minecraft-safe capture mode: game capture only for {label}.")
                elif self.obs_capture_strategy == "game_only":
                    self.log(f"OBS capture recovery: game capture only for {label}.")
                elif specific_window and use_game_capture:
                    selector = self.obs_window_selector_from_context(context)
                    self.log(f"OBS capture mode: specific game window with {method_label} display fallback ({selector or label}).")
                elif use_game_capture:
                    self.log(f"OBS capture mode: game capture with live {method_label} display fallback for {label}.")
                elif base_mode == "browser_display":
                    self.log(f"OBS browser capture mode: {method_label} display capture for {label}.")
                elif self.obs_capture_strategy in {"display_auto", "display_wgc"}:
                    self.log(f"OBS capture recovery: {method_label} display capture only for {label}.")
                else:
                    self.log(f"OBS capture mode: {method_label} display capture only.")
        except Exception as exc:
            self.warn_once(f"obs_scene_capture_selection_{mode}", f"OBS capture source switch failed: {exc}")

    def configure_obs_for_capture(self):
        obs_exe = self.require_obs()
        self.write_obs_capture_profile_config(self.obs_root_dir(obs_exe))
        client = self.ensure_obs_runtime()
        width, height = self.obs_video_size()
        fps = max(1, int(self.config.get("framerate", 60) or 60))
        output_dir = str(self.obs_output_dir())
        container = str(self.config.get("container", "mp4")).casefold()
        obs_format = "hybrid_mp4" if container == "mp4" else "mkv"
        bitrate = max(1000, int(self.config.get("video_bitrate_mbps", 35) or 35) * 1000)
        clip_seconds = max(1, int(self.config.get("clip_seconds", 30) or 30))
        replay_buffer_mb = self.obs_replay_buffer_mb()
        output_active = self.obs_output_active(client)

        for category, name, value in [] if output_active else [
            ("SimpleOutput", "FilePath", output_dir),
            ("SimpleOutput", "RecFormat2", obs_format),
            ("SimpleOutput", "VBitrate", str(bitrate)),
            ("SimpleOutput", "RecRB", "true"),
            ("SimpleOutput", "RecRBTime", str(clip_seconds)),
            ("SimpleOutput", "RecRBSize", str(replay_buffer_mb)),
            ("Output", "Mode", "Simple"),
        ]:
            try:
                client.request("SetProfileParameter", {
                    "parameterCategory": category,
                    "parameterName": name,
                    "parameterValue": value,
                })
            except Exception as exc:
                self.warn_once(f"obs_profile_{category}_{name}", f"OBS profile parameter {category}/{name} failed: {exc}")

        if output_active:
            self.warn_once("obs_output_active_config", "OBS output is active; keeping current OBS video/output settings.")
        else:
            estimated_clip_mb = self.obs_estimated_clip_mb()
            if estimated_clip_mb and replay_buffer_mb < estimated_clip_mb:
                self.warn_once(
                    "obs_replay_buffer_low",
                    f"OBS replay RAM limit is {replay_buffer_mb} MB; this may shorten clips at the current bitrate/length.",
                )
            self.log(f"OBS replay RAM limit: {replay_buffer_mb} MB.")
            try:
                client.request("SetRecordDirectory", {"recordDirectory": output_dir})
            except Exception as exc:
                self.warn_once("obs_record_directory", f"OBS record directory setup failed: {exc}")

            self.set_obs_video_settings_for_size(client, width, height)

        scenes = client.request("GetSceneList").get("scenes", [])
        scene_names = {scene.get("sceneName") for scene in scenes}
        if self.obs_scene_name not in scene_names:
            client.request("CreateScene", {"sceneName": self.obs_scene_name})
        client.request("SetCurrentProgramScene", {"sceneName": self.obs_scene_name})

        inputs = client.request("GetInputList").get("inputs", [])
        input_names = {source.get("inputName") for source in inputs}
        initial_base_mode, initial_context = self.obs_capture_source_mode()
        self.prepare_obs_capture_context(initial_context)
        initial_use_game_capture = self.obs_strategy_uses_game_capture(initial_base_mode)
        initial_specific_window = self.obs_strategy_uses_specific_window(initial_base_mode)
        initial_display_enabled = self.obs_capture_strategy != "game_only"
        display_settings = self.obs_display_input_settings(initial_context)
        if self.obs_display_input_name not in input_names:
            try:
                client.request("CreateInput", {
                    "sceneName": self.obs_scene_name,
                    "inputName": self.obs_display_input_name,
                    "inputKind": "monitor_capture",
                    "inputSettings": display_settings,
                    "sceneItemEnabled": initial_display_enabled,
                })
                input_names.add(self.obs_display_input_name)
                self.obs_display_monitor_id = str(display_settings.get("monitor_id") or "") or None
                self.obs_display_settings_signature = json.dumps(display_settings, sort_keys=True, ensure_ascii=False)
            except Exception as exc:
                self.warn_once("obs_monitor_fallback", f"OBS monitor fallback setup failed: {exc}")
        elif initial_display_enabled:
            self.update_obs_display_input_settings(client, context=initial_context, force=True)

        settings = self.obs_game_input_settings(
            context=initial_context,
            minecraft_specific=initial_specific_window,
        )
        if self.obs_game_input_name not in input_names:
            client.request("CreateInput", {
                "sceneName": self.obs_scene_name,
                "inputName": self.obs_game_input_name,
                "inputKind": "game_capture",
                "inputSettings": settings,
                "sceneItemEnabled": initial_use_game_capture,
            })
            self.obs_game_settings_signature = json.dumps(settings, sort_keys=True, ensure_ascii=False)
        elif initial_use_game_capture:
            self.update_obs_game_input_settings(
                client,
                context=initial_context,
                minecraft_specific=initial_specific_window,
                force=True,
            )
        if initial_display_enabled:
            self.set_obs_scene_item_full_canvas_transform(client, self.obs_display_input_name, force=True)
        self.set_obs_scene_item_full_canvas_transform(client, self.obs_game_input_name, force=True)
        self.update_obs_scene_capture_selection(client, force=True)
        self.log("OBS scene ready.")
        self.warn_once(
            "obs_live_screenshot_probe_disabled",
            "OBS live screenshot health probes are disabled for win-capture stability.",
        )
        return client

    def obs_source_screenshot_metrics(self, client, source_name):
        response = client.request("GetSourceScreenshot", {
            "sourceName": source_name,
            "imageFormat": "png",
            "imageWidth": 160,
            "imageHeight": 90,
            "imageCompressionQuality": -1,
        })
        return png_visual_metrics(response.get("imageData"))

    def set_obs_capture_strategy(self, client, strategy, reason):
        if strategy == self.obs_capture_strategy:
            return False
        previous = self.obs_capture_strategy
        self.obs_capture_strategy = strategy
        self.obs_capture_strategy_changed_at = time.time()
        self.obs_capture_last_probe_at = 0.0
        self.obs_capture_black_samples = 0
        self.obs_capture_good_samples = 0
        self.obs_capture_recovery_pending_reset = True
        self.obs_capture_unresolved_logged = False
        self.obs_scene_capture_mode = None
        self.obs_display_settings_signature = None
        self.update_obs_scene_capture_selection(client, force=True)
        self.obs_replay_watchdog_grace_until = time.time() + 5.0
        self.log(f"OBS black-screen recovery: {previous} -> {strategy}. {reason}")
        return True

    def advance_obs_black_screen_recovery(self, client, base_mode, display_metrics=None):
        use_game_capture = self.obs_strategy_uses_game_capture(base_mode)
        display_is_black = not display_metrics or bool(display_metrics.get("black"))
        if self.obs_capture_strategy == "overlay_wgc":
            if use_game_capture:
                return self.set_obs_capture_strategy(
                    client,
                    "game_only",
                    "The WGC desktop-overlay layer stayed black; falling back to the underlying game capture.",
                )
            return self.set_obs_capture_strategy(
                client,
                "display_auto",
                "The WGC desktop-overlay layer stayed black; retrying automatic display capture.",
            )
        if self.obs_capture_strategy == "game_only":
            return self.set_obs_capture_strategy(
                client,
                "display_auto",
                "Game Capture also stayed black; retrying Automatic/DXGI display capture.",
            )
        if self.obs_capture_strategy == "auto":
            if use_game_capture and not display_is_black:
                return self.set_obs_capture_strategy(
                    client,
                    "display_auto",
                    "Game Capture was black while the live display fallback had a valid picture.",
                )
            return self.set_obs_capture_strategy(
                client,
                "display_wgc",
                "The current game/display path stayed black; switching the monitor source to Windows Graphics Capture.",
            )
        if self.obs_capture_strategy == "display_auto":
            return self.set_obs_capture_strategy(
                client,
                "display_wgc",
                "Automatic/DXGI display capture stayed black; switching to Windows Graphics Capture.",
            )
        if self.obs_capture_strategy == "display_wgc" and base_mode in {"game_capture", "minecraft_game_capture"}:
            return self.set_obs_capture_strategy(
                client,
                "game_window_wgc",
                "WGC display capture stayed black; retrying OBS Game Capture against the exact foreground window.",
            )
        if not self.obs_capture_unresolved_logged:
            self.obs_capture_unresolved_logged = True
            self.log(
                "OBS black-screen recovery exhausted all generic capture paths for the active application. "
                "Exclusive/protected rendering or an elevated game process may still prevent capture."
            )
        return False

    def finish_obs_capture_recovery(self, client):
        self.obs_capture_strategy_cache[self.obs_capture_context_key] = self.obs_capture_strategy
        if not self.obs_capture_recovery_pending_reset:
            return
        self.obs_capture_recovery_pending_reset = False
        try:
            if self.obs_replay_buffer_active(client):
                self.reset_obs_replay_buffer(client)
                self.log(
                    f"OBS capture recovered with strategy '{self.obs_capture_strategy}'. "
                    "Replay window reset so future clips do not contain the detected black frames."
                )
            else:
                self.log(f"OBS capture recovered with strategy '{self.obs_capture_strategy}'.")
        except Exception as exc:
            self.log(f"OBS capture recovered, but replay cleanup failed: {exc}")

    def check_obs_capture_health(self, client, force=False):
        # Do not issue GetSourceScreenshot against live win-capture sources.
        # Six matching OBS 32.1.2 crash logs showed the request racing Minecraft's
        # OpenGL hook reconnect at win-capture.dll + 0x9D4B.
        return None

    def start_obs_replay(self, preserve_buffer=False, from_watchdog=False):
        client = self.configure_obs_for_capture()
        if not preserve_buffer:
            self.last_clip_saved_at = 0.0
            self.replay_backend_override = None
            self.replay_restart_count = 0
        self.start_obs_replay_buffer_with_retry(client)
        self.replay_proc = VirtualProcess("obs replay")
        self.replay_active_backend = "obs"
        self.replay_should_restart = True
        self.stop_cleanup.set()
        self.log("Replay capture backend: obs.")
        if from_watchdog:
            self.log("Replay buffer restarted.")
        else:
            self.log("Replay buffer started.")
        self.start_obs_replay_watchdog(self.replay_proc)

    def stop_obs_replay(self):
        try:
            client = self.ensure_obs_runtime()
            status = client.request("GetReplayBufferStatus")
            if status.get("outputActive"):
                client.request("StopReplayBuffer")
        except Exception as exc:
            self.log(f"OBS replay stop failed: {exc}")
        if self.replay_proc:
            self.replay_proc.mark_stopped(0)
        self.replay_proc = None
        self.replay_active_backend = None
        self.replay_should_restart = False
        self.log("Stopped replay.")

    def start_obs_replay_buffer_with_retry(self, client, attempts=5):
        last_error = None
        for attempt in range(max(1, attempts)):
            try:
                status = client.request("GetReplayBufferStatus")
                if status.get("outputActive"):
                    return True
                client.request("StartReplayBuffer")
                if self.wait_for_obs_replay_buffer_active(client, timeout=3.5 + attempt * 0.5):
                    self.obs_replay_watchdog_grace_until = time.time() + 4.0
                    return True
                last_error = RuntimeError("OBS replay buffer did not become active after StartReplayBuffer.")
            except Exception as exc:
                last_error = exc
                time.sleep(0.35 + attempt * 0.15)
        raise RuntimeError(str(last_error or "unknown OBS replay start error"))

    def reset_obs_replay_buffer(self, client):
        self.obs_replay_resetting = True
        try:
            status = client.request("GetReplayBufferStatus")
            if status.get("outputActive"):
                client.request("StopReplayBuffer")
                deadline = time.time() + 4.0
                while time.time() < deadline:
                    try:
                        status = client.request("GetReplayBufferStatus")
                        if not status.get("outputActive"):
                            break
                    except Exception:
                        break
                    time.sleep(0.15)
            self.start_obs_replay_buffer_with_retry(client)
            self.obs_replay_watchdog_grace_until = time.time() + 4.0
        finally:
            self.obs_replay_resetting = False

    def restart_inactive_obs_replay_for_next_clip(self, client, reason):
        try:
            self.start_obs_replay_buffer_with_retry(client)
            if self.replay_proc and self.replay_proc.poll() is not None:
                self.replay_proc = VirtualProcess("obs replay")
            self.replay_active_backend = "obs"
            self.replay_should_restart = True
            self.log(f"{reason} OBS replay buffer restarted; wait a few seconds and save again.")
        except Exception as exc:
            self.log(f"{reason} OBS replay buffer restart failed: {exc}")

    def start_obs_replay_watchdog(self, proc):
        if not bool(self.config.get("replay_auto_restart", True)):
            return
        thread = threading.Thread(target=self.obs_replay_watchdog_loop, args=(proc,), daemon=True)
        self.replay_watchdog_thread = thread
        thread.start()

    def obs_replay_watchdog_loop(self, proc):
        while self.replay_should_restart and self.replay_proc is proc:
            time.sleep(2.0)
            if not self.replay_should_restart or self.replay_proc is not proc:
                return
            if self.obs_replay_resetting:
                continue
            try:
                client = self.ensure_obs_runtime()
                if self.ensure_obs_canvas_matches_monitor(client):
                    continue
                self.update_obs_scene_capture_selection(client)
                if time.time() < self.obs_replay_watchdog_grace_until:
                    continue
                if not self.obs_replay_buffer_active(client):
                    self.log("OBS replay buffer stopped unexpectedly; restarting.")
                    self.start_obs_replay_buffer_with_retry(client)
                    self.log("OBS replay buffer restarted by watchdog.")
                    continue
            except Exception as exc:
                key = f"obs_replay_watchdog:{type(exc).__name__}:{str(exc)[:80]}"
                if key not in self.warning_keys:
                    self.warning_keys.add(key)
                    self.log(f"OBS replay watchdog warning: {exc}")

    def save_obs_clip(self):
        client = self.ensure_obs_runtime()
        self.update_obs_scene_capture_selection(client)
        if not self.obs_replay_buffer_active(client):
            self.restart_inactive_obs_replay_for_next_clip(client, "OBS replay buffer was inactive before saving.")
            return
        before_path = ""
        try:
            before_path = str(client.request("GetLastReplayBufferReplay").get("savedReplayPath") or "")
        except Exception:
            pass

        try:
            client.request("SaveReplayBuffer")
        except Exception as exc:
            if "501" in str(exc) or "not running" in str(exc).casefold():
                self.restart_inactive_obs_replay_for_next_clip(client, "OBS replay buffer was inactive during save.")
                return
            raise
        saved_path = ""
        deadline = time.time() + 15.0
        while time.time() < deadline:
            try:
                saved_path = str(client.request("GetLastReplayBufferReplay").get("savedReplayPath") or "")
                if saved_path and saved_path != before_path and Path(saved_path).exists():
                    break
            except Exception:
                pass
            time.sleep(0.1)
        if not saved_path:
            raise RuntimeError("OBS did not report a saved replay path.")

        output = self.organize_saved_obs_media(Path(saved_path))
        self.last_clip_path = output
        now = time.time()
        self.last_clip_saved_at = now
        self.log(f"Clip saved (OBS replay): {output}")
        self.schedule_output_storage_cleanup()
        if bool(self.config.get("reset_replay_after_clip", True)):
            try:
                self.reset_obs_replay_buffer(client)
                self.log("Replay window reset; the next clip will save only new OBS replay time.")
            except Exception as exc:
                self.log(f"OBS replay reset failed: {exc}")

    def start_obs_recording(self):
        if self.record_proc and self.record_proc.poll() is None:
            self.log("Recording already running.")
            return
        client = self.configure_obs_for_capture()
        status = client.request("GetRecordStatus")
        if not status.get("outputActive"):
            client.request("StartRecord")
        self.record_proc = VirtualProcess("obs recording")
        self.recording_active_backend = "obs"
        self.recording_started_at = time.time()
        self.current_recording_path = None
        self.recording_uses_separate_audio = False
        self.recording_audio_owned = False
        self.log("Recording capture backend: obs.")
        self.log(f"Recording started: {self.obs_output_dir()}")
        thread = threading.Thread(target=self.obs_recording_capture_watchdog_loop, args=(self.record_proc,), daemon=True)
        self.obs_record_watchdog_thread = thread
        thread.start()

    def obs_recording_capture_watchdog_loop(self, proc):
        while self.record_proc is proc and proc.poll() is None:
            time.sleep(2.0)
            if self.record_proc is not proc or proc.poll() is not None:
                return
            if self.replay_active_backend == "obs" and self.replay_proc and self.replay_proc.poll() is None:
                continue
            if self.obs_replay_resetting:
                continue
            try:
                client = self.ensure_obs_runtime()
                self.update_obs_scene_capture_selection(client)
            except Exception as exc:
                key = f"obs_record_capture_watchdog:{type(exc).__name__}:{str(exc)[:80]}"
                if key not in self.warning_keys:
                    self.warning_keys.add(key)
                    self.log(f"OBS recording capture watchdog warning: {exc}")

    def stop_obs_recording(self):
        if not self.record_proc or self.record_proc.poll() is not None:
            self.log("No recording running.")
            return
        output_path = ""
        try:
            client = self.ensure_obs_runtime()
            status = client.request("GetRecordStatus")
            if status.get("outputActive"):
                response = client.request("StopRecord")
                output_path = str(response.get("outputPath") or "")
        except Exception as exc:
            self.log(f"OBS recording stop failed: {exc}")
        if self.record_proc:
            self.record_proc.mark_stopped(0)
        self.record_proc = None
        self.recording_started_at = None
        self.current_recording_path = None
        self.recording_active_backend = None
        self.recording_uses_separate_audio = False
        self.recording_audio_owned = False
        if output_path:
            output_path = str(self.organize_saved_obs_media(Path(output_path)))
            self.log(f"OBS recording saved: {output_path}")
        self.schedule_output_storage_cleanup()
        self.log("Stopped recording.")

    def _stop_obs_runtime_locked(self):
        if self.obs_client:
            try:
                self.obs_client.close()
            except Exception:
                pass
            self.obs_client = None
        if self.obs_proc and self.obs_proc.poll() is None:
            try:
                self.obs_proc.terminate()
                self.obs_proc.wait(timeout=5)
            except Exception:
                try:
                    self.obs_proc.kill()
                except Exception:
                    pass
        self.obs_proc = None
        self.obs_process_started_at = 0.0
        self.obs_frontend_ready = False

    def stop_obs_runtime(self):
        with self.obs_runtime_lock:
            self._stop_obs_runtime_locked()

    def probe_duration(self, media_path):
        ffprobe = self.find_ffprobe()
        if not ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(media_path),
                ],
                capture_output=True,
                text=True,
                timeout=12,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            return None
        return None

    def has_audio_stream(self, media_path):
        ffprobe = self.find_ffprobe()
        if not ffprobe:
            return False
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    str(media_path),
                ],
                capture_output=True,
                text=True,
                timeout=12,
                creationflags=CREATE_NO_WINDOW,
            )
            return bool(result.stdout.strip())
        except Exception:
            return False

    def has_video_stream(self, media_path):
        ffprobe = self.find_ffprobe()
        if not ffprobe:
            return False
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    str(media_path),
                ],
                capture_output=True,
                text=True,
                timeout=12,
                creationflags=CREATE_NO_WINDOW,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            return False

    def available_ffmpeg_video_encoders(self):
        if self.ffmpeg_encoder_names_cache is not None:
            return self.ffmpeg_encoder_names_cache
        names = set()
        try:
            ffmpeg = self.require_ffmpeg()
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            output = result.stdout + result.stderr
            for encoder in VIDEO_ENCODER_VALUES:
                if encoder != "auto" and re.search(rf"\b{re.escape(encoder)}\b", output):
                    names.add(encoder)
        except Exception:
            names = set()
        if not names:
            names.add("libx264")
        self.ffmpeg_encoder_names_cache = names
        return names

    def detect_gpu_adapter_names(self):
        if self.gpu_adapter_names_cache is not None:
            return self.gpu_adapter_names_cache
        names = []
        commands = [
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command",
                "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }",
            ],
            ["wmic", "path", "win32_VideoController", "get", "name"],
        ]
        for command in commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=6,
                    creationflags=CREATE_NO_WINDOW,
                )
            except Exception:
                continue
            for line in (result.stdout or "").splitlines():
                cleaned = line.strip()
                if not cleaned or cleaned.casefold() == "name" or set(cleaned) == {"-"}:
                    continue
                names.append(cleaned)
            if names:
                break
        self.gpu_adapter_names_cache = names
        return names

    def gpu_encoder_preference(self):
        adapters = "\n".join(self.detect_gpu_adapter_names()).casefold()
        preference = []

        def add(encoder):
            if encoder not in preference:
                preference.append(encoder)

        if "nvidia" in adapters:
            add("h264_nvenc")
        if any(token in adapters for token in ("amd", "radeon", "advanced micro devices")):
            add("h264_amf")
        if "intel" in adapters:
            add("h264_qsv")
        for encoder in HARDWARE_VIDEO_ENCODERS:
            add(encoder)
        return preference

    def log_video_encoder_choice(self, encoder, requested):
        signature = (normalize_video_encoder(requested), encoder)
        if self.encoder_log_signature == signature:
            return
        mode = "hardware" if encoder in HARDWARE_VIDEO_ENCODERS else "software"
        self.log(f"Selected {mode} encoder: {video_encoder_label(encoder)}.")
        self.encoder_log_signature = signature

    def resolve_video_encoder(self, ffmpeg_limited=True, log_selection=False):
        requested = normalize_video_encoder(self.config.get("video_encoder", "auto"))
        available = (
            self.available_ffmpeg_video_encoders()
            if ffmpeg_limited
            else set(VIDEO_ENCODER_VALUES) - {"auto"}
        )
        if requested != "auto":
            if requested in available:
                encoder = requested
            else:
                self.warn_once(
                    f"encoder_unavailable_{requested}",
                    f"Configured encoder {video_encoder_label(requested)} is not available; falling back to auto.",
                )
                requested = "auto"
        if requested == "auto":
            encoder = "libx264"
            for candidate in self.gpu_encoder_preference():
                if candidate in available:
                    encoder = candidate
                    break
            if encoder == "libx264" and "libx264" not in available:
                encoder = next(iter(available), "libx264")
        if ffmpeg_limited:
            self.encoder_cache = encoder
        if log_selection:
            self.log_video_encoder_choice(encoder, requested)
        return encoder

    def detect_encoder(self):
        requested = normalize_video_encoder(self.config.get("video_encoder", "auto"))
        if requested == "auto" and self.encoder_cache:
            return self.encoder_cache
        return self.resolve_video_encoder(ffmpeg_limited=True, log_selection=True)

    def detect_ddagrab(self):
        if self.ddagrab_cache is not None:
            return self.ddagrab_cache
        ffmpeg = self.require_ffmpeg()
        try:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-filters"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            filters = result.stdout + result.stderr
            self.ddagrab_cache = "ddagrab" in filters
        except Exception:
            self.ddagrab_cache = False
        return self.ddagrab_cache

    def capture_backend(self, backend_override=None):
        requested = backend_override or self.config.get("capture_backend", "auto")
        if backend_override is None and bool(
            self.config.get("capture_desktop_overlays", DEFAULT_CONFIG["capture_desktop_overlays"])
        ):
            requested = "obs"
        mode = self.config.get("capture_mode", "desktop_all")
        if requested == "ddagrab":
            if mode != "monitor":
                raise RuntimeError("DDA backend currently supports one-monitor capture only.")
            if not self.detect_ddagrab():
                raise RuntimeError("FFmpeg build does not include ddagrab.")
            return "ddagrab"
        if requested == "gdigrab":
            return "gdigrab"
        if requested == "obs":
            return "obs"
        if mode == "monitor" and self.detect_ddagrab():
            return "ddagrab"
        return "gdigrab"

    def capture_backend_fallback(self, backend):
        if self.config.get("capture_backend", "auto") != "auto":
            return None
        if backend == "ddagrab":
            return "gdigrab"
        return None

    def scan_audio_devices(self):
        ffmpeg = self.require_ffmpeg()
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=CREATE_NO_WINDOW,
        )
        text = result.stdout + result.stderr
        devices = []
        for line in text.splitlines():
            match = re.search(r'"(.+?)"\s+\(audio\)', line)
            if match:
                devices.append(match.group(1))
        return sorted(set(devices), key=str.casefold), text

    def scan_wasapi_loopbacks(self):
        if sc is None:
            return []
        try:
            loopbacks = sc.all_microphones(include_loopback=True)
            devices = [device.name for device in loopbacks if getattr(device, "isloopback", False)]
            return sorted(set(devices), key=str.casefold)
        except Exception as exc:
            self.warn_once("wasapi_scan_failed", f"WASAPI desktop audio scan failed: {exc}")
            return []

    def scan_soundcard_mics(self):
        if sc is None:
            return []
        try:
            mics = sc.all_microphones(include_loopback=False)
            devices = [device.name for device in mics if not getattr(device, "isloopback", False)]
            return sorted(set(devices), key=str.casefold)
        except Exception as exc:
            self.warn_once("soundcard_mic_scan_failed", f"WASAPI mic scan failed: {exc}")
            return []

    def uses_wasapi_desktop_audio(self):
        return bool(
            self.config.get("desktop_audio_enabled")
            and self.config.get("desktop_audio_backend", "wasapi") == "wasapi"
        )

    def uses_soundcard_mic_audio(self):
        return bool(self.config.get("mic_enabled") and sc is not None and np is not None)

    def separate_audio_sources(self):
        sources = []
        if self.uses_wasapi_desktop_audio():
            sources.append({
                "key": "desktop",
                "prefix": "desktop",
                "label": "WASAPI desktop audio",
                "device_name": str(self.config.get("desktop_audio_device", "")).strip(),
                "include_loopback": True,
                "channels": 2,
            })
        if self.uses_soundcard_mic_audio():
            mic = str(self.config.get("mic_device", "")).strip()
            if not mic:
                self.warn_once("missing_mic_device", "Mic is enabled, but no mic device is selected; skipping mic audio.")
            else:
                sources.append({
                    "key": "mic",
                    "prefix": "mic",
                    "label": "WASAPI mic audio",
                    "device_name": mic,
                    "include_loopback": False,
                    "channels": 1,
                })
        return sources

    def has_separate_audio_capture(self):
        return bool(sc is not None and np is not None and self.separate_audio_sources())

    def gdigrab_input_args(self, fps):
        return [
            "-thread_queue_size", "1024",
            "-probesize", "50M",
            "-f", "gdigrab",
            "-framerate", fps,
            "-draw_mouse", "1",
        ]

    def dshow_audio_input_args(self, device):
        return [
            "-thread_queue_size", "2048",
            "-rtbufsize", "256M",
            "-f", "dshow",
            "-audio_buffer_size", "50",
            "-i", f"audio={device}",
        ]

    def common_input_args(self, include_audio=True, separate_audio=False, backend_override=None):
        mode = self.config.get("capture_mode", "desktop_all")
        fps = str(int(self.config.get("framerate", 60)))
        backend = self.capture_backend(backend_override)
        args = []

        if backend == "ddagrab":
            monitors = enum_monitors()
            if not monitors:
                raise RuntimeError("No monitor found.")
            index = int(self.config.get("monitor_index", 0))
            index = max(0, min(index, len(monitors) - 1))
            args += [
                "-f", "lavfi",
                "-i", f"ddagrab=output_idx={index}:framerate={fps}:draw_mouse=1",
            ]
        elif mode == "window":
            args += self.gdigrab_input_args(fps)
            title = str(self.config.get("window_title", "")).strip()
            if not title:
                raise RuntimeError("Window/Game mode needs a window title.")
            args += ["-i", f"title={title}"]
        elif mode == "monitor":
            args += self.gdigrab_input_args(fps)
            monitors = enum_monitors()
            if not monitors:
                raise RuntimeError("No monitor found.")
            index = int(self.config.get("monitor_index", 0))
            index = max(0, min(index, len(monitors) - 1))
            monitor = monitors[index]
            args += [
                "-offset_x", str(monitor["left"]),
                "-offset_y", str(monitor["top"]),
                "-video_size", f"{monitor['width']}x{monitor['height']}",
                "-i", "desktop",
            ]
        else:
            args += self.gdigrab_input_args(fps)
            args += ["-i", "desktop"]

        for device in self.direct_audio_input_devices(separate_audio=separate_audio) if include_audio else []:
            args += self.dshow_audio_input_args(device)
        return args

    def direct_audio_input_devices(self, separate_audio=False):
        devices = []
        if self.config.get("mic_enabled") and not (separate_audio and self.uses_soundcard_mic_audio()):
            mic = str(self.config.get("mic_device", "")).strip()
            if not mic:
                self.warn_once("missing_mic_device", "Mic is enabled, but no mic device is selected; skipping mic audio.")
            else:
                devices.append(mic)

        if self.config.get("desktop_audio_enabled"):
            if self.config.get("desktop_audio_backend", "wasapi") == "wasapi":
                pass
            else:
                desktop = str(self.config.get("desktop_audio_device", "")).strip()
                if not desktop:
                    self.warn_once("missing_desktop_audio_device", "Desktop audio is enabled, but no desktop/loopback device is selected; skipping desktop audio.")
                else:
                    devices.append(desktop)

        if not devices and self.config.get("audio_mode") == "dshow" and not (
            self.config.get("mic_enabled") or self.config.get("desktop_audio_enabled")
        ):
            legacy = str(self.config.get("audio_device", "")).strip()
            if not legacy:
                raise RuntimeError("DirectShow audio is enabled, but no audio device is selected.")
            devices.append(legacy)

        unique = []
        for device in devices:
            if device and device not in unique:
                unique.append(device)
        return unique

    def warn_once(self, key, message):
        if key not in self.warning_keys:
            self.warning_keys.add(key)
            self.log(message)

    def output_map_args(self, include_audio=True, separate_audio=False):
        audio_devices = self.direct_audio_input_devices(separate_audio=separate_audio) if include_audio else []
        if len(audio_devices) > 1:
            inputs = "".join(f"[{index}:a:0]" for index in range(1, len(audio_devices) + 1))
            return [
                "-filter_complex",
                f"{inputs}amix=inputs={len(audio_devices)}:duration=longest:dropout_transition=0[aout]",
                "-map", "0:v:0",
                "-map", "[aout]",
            ]
        args = ["-map", "0:v:0"]
        if len(audio_devices) == 1:
            args += ["-map", "1:a:0"]
        return args

    def audio_source_dir(self, source):
        return self.audio_base_dir / source["key"]

    def resolve_soundcard_device(self, source):
        device_name = source["device_name"]
        include_loopback = bool(source["include_loopback"])
        if include_loopback and not device_name:
            return sc.get_microphone(sc.default_speaker().name, include_loopback=True)
        if device_name:
            try:
                return sc.get_microphone(device_name, include_loopback=include_loopback)
            except Exception:
                devices = sc.all_microphones(include_loopback=include_loopback)
                wanted = device_name.casefold()
                for device in devices:
                    if device.name.casefold() == wanted:
                        return device
                for device in devices:
                    name = device.name.casefold()
                    if wanted in name or name in wanted:
                        return device
                raise
        return sc.default_microphone()

    def start_audio_capture(self, clear_existing=True):
        sources = self.separate_audio_sources()
        if not sources:
            return
        if sc is None or np is None:
            self.warn_once("soundcard_missing", "WASAPI audio is enabled, but the bundled soundcard runtime is unavailable.")
            return
        if any(thread.is_alive() for thread in self.audio_threads.values()):
            return

        self.audio_base_dir.mkdir(parents=True, exist_ok=True)
        for source in sources:
            directory = self.audio_source_dir(source)
            directory.mkdir(parents=True, exist_ok=True)
            if clear_existing:
                for segment in directory.glob(f"{source['prefix']}_*.wav"):
                    try:
                        segment.unlink()
                    except OSError:
                        pass

        self.audio_stop.clear()
        self.audio_threads = {}
        for source in sources:
            thread = threading.Thread(target=self._audio_capture_loop, args=(source,), daemon=True)
            self.audio_threads[source["key"]] = thread
            thread.start()

    def stop_audio_capture(self):
        self.audio_stop.set()
        for thread in list(self.audio_threads.values()):
            if thread.is_alive():
                thread.join(timeout=3)
        self.audio_threads = {}

    def _audio_capture_loop(self, source):
        sample_rate = 48000
        frames_per_segment = sample_rate
        directory = self.audio_source_dir(source)
        prefix = source["prefix"]
        channels = int(source["channels"])
        try:
            recorder_device = self.resolve_soundcard_device(source)
            self.log(f"{source['label']} started: {recorder_device.name}")
            with recorder_device.recorder(samplerate=sample_rate, channels=channels) as recorder:
                while not self.audio_stop.is_set():
                    start = time.time()
                    data = recorder.record(numframes=frames_per_segment)
                    end = time.time()
                    if data is None or not getattr(data, "size", 0):
                        continue
                    frame_count = int(data.shape[0]) if hasattr(data, "shape") and data.shape else frames_per_segment
                    actual_duration = frame_count / sample_rate
                    segment_start = end - actual_duration
                    path = directory / f"{prefix}_{int(segment_start * 1000)}_{int(end * 1000)}.wav"
                    temp_path = path.with_name(f"{path.stem}.{threading.get_ident()}.tmp.wav")
                    try:
                        write_float_wav(temp_path, data, sample_rate)
                        replace_with_retries(temp_path, path)
                    except Exception as exc:
                        self.warn_once(f"{prefix}_write_failed", f"{source['label']} write failed: {exc}")
                        try:
                            temp_path.unlink()
                        except OSError:
                            pass
        except Exception as exc:
            self.warn_once(f"{prefix}_record_failed", f"{source['label']} failed: {exc}")

    def matching_audio_segments(self, source, clip_start, clip_end):
        matches = []
        directory = self.audio_source_dir(source)
        for segment in sorted(directory.glob(f"{source['prefix']}_*.wav")):
            parsed = parse_audio_segment_times(segment)
            if not parsed:
                continue
            start, end = parsed
            if end > clip_start and start < clip_end:
                matches.append((segment, start, end))
        return matches

    def separate_audio_offset_ms(self, context_label="Clip"):
        if context_label == "Recording":
            return int(self.config.get("recording_audio_offset_ms", self.config.get("audio_offset_ms", 0)) or 0)
        return int(self.config.get("audio_offset_ms", 0) or 0)

    def prepare_audio_source(self, ffmpeg, source, trim_duration, clip_start, clip_end, log_handle, context_label="Clip"):
        matches = self.matching_audio_segments(source, clip_start, clip_end)
        prefix = source["prefix"]
        self.log(f"{context_label} audio source {source['label']}: {len(matches)} segment(s) matched.")
        if not matches:
            self.log(f"{context_label} audio source {source['label']} skipped: no finalized segment matched the save window.")
            return None, []

        list_path = None
        joined_audio = self.runtime_dir / timestamp_name(f"{prefix}_joined", "wav")
        trimmed_audio = self.runtime_dir / timestamp_name(f"{prefix}_trimmed", "wav")
        cleanup_paths = []
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
                list_path = Path(handle.name)
                cleanup_paths.append(list_path)
                for segment, _start, _end in matches:
                    safe_path = segment.resolve().as_posix().replace("'", "'\\''")
                    handle.write(f"file '{safe_path}'\n")

            concat_result = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel", "warning",
                    "-y",
                    "-safe", "0",
                    "-f", "concat",
                    "-i", str(list_path),
                    "-c:a", "pcm_s16le",
                    str(joined_audio),
                ],
                stdout=subprocess.DEVNULL,
                stderr=log_handle,
                creationflags=CREATE_NO_WINDOW,
            )
            cleanup_paths.append(joined_audio)
            if concat_result.returncode != 0:
                self.log(f"{context_label} audio source {source['label']} concat failed; saving without that source.")
                return None, cleanup_paths

            first_start = matches[0][1]
            last_end = matches[-1][2]
            configured_offset_ms = self.separate_audio_offset_ms(context_label)
            configured_offset = configured_offset_ms / 1000.0
            audio_gap = first_start - clip_start + configured_offset
            leading_gap = first_start - clip_start
            trailing_gap = clip_end - last_end
            log_handle.write(
                f"{source['label']} sync: offset_ms={configured_offset_ms}, "
                f"clip_start={clip_start:.3f}, first_audio_start={first_start:.3f}, "
                f"last_audio_end={last_end:.3f}, clip_end={clip_end:.3f}, "
                f"leading_gap={leading_gap:.3f}, trailing_gap={trailing_gap:.3f}, "
                f"audio_gap={audio_gap:.3f}\n"
            )
            log_handle.flush()
            if leading_gap > 2.0:
                self.log(
                    f"{context_label} audio source {source['label']} starts {leading_gap:.1f}s after the video window; "
                    "earlier audio was not available."
                )
            if trailing_gap > 2.0:
                self.log(
                    f"{context_label} audio source {source['label']} ends {trailing_gap:.1f}s before the video window; "
                    "later audio was not available."
                )
            trim_cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "warning",
                "-y",
            ]
            if audio_gap > 0.02:
                delay_ms = int(round(audio_gap * 1000))
                trim_cmd += ["-i", str(joined_audio)]
                audio_filter = f"adelay={delay_ms}:all=1,apad,atrim=0:{trim_duration:.3f}"
            else:
                seek_start = max(-audio_gap, 0)
                trim_cmd += ["-ss", f"{seek_start:.3f}", "-i", str(joined_audio)]
                audio_filter = f"apad,atrim=0:{trim_duration:.3f}"
            trim_cmd += [
                "-filter:a", audio_filter,
                "-c:a", "pcm_s16le",
                str(trimmed_audio),
            ]
            trim_result = subprocess.run(
                trim_cmd,
                stdout=subprocess.DEVNULL,
                stderr=log_handle,
                creationflags=CREATE_NO_WINDOW,
            )
            if trim_result.returncode != 0:
                self.log(f"{context_label} audio source {source['label']} trim failed; saving without that source.")
                return None, cleanup_paths
            return trimmed_audio, cleanup_paths + [trimmed_audio]
        except Exception as exc:
            self.log(f"{context_label} audio source {source['label']} prepare failed: {exc}")
            return None, cleanup_paths

    def add_separate_audio(self, ffmpeg, output, trim_duration, clip_start, clip_end, log_handle, context_label="Clip"):
        sources = self.separate_audio_sources()
        if not sources:
            return []

        trimmed_sources = []
        cleanup_paths = []
        merged_output = output.with_name(output.stem + "_audiomix" + output.suffix)
        try:
            for source in sources:
                trimmed_audio, paths = self.prepare_audio_source(
                    ffmpeg,
                    source,
                    trim_duration,
                    clip_start,
                    clip_end,
                    log_handle,
                    context_label=context_label,
                )
                cleanup_paths.extend(paths)
                if trimmed_audio:
                    trimmed_sources.append((trimmed_audio, source["label"]))

            if not trimmed_sources:
                self.log(f"{context_label} audio merge skipped: no prepared audio sources.")
                return []

            merge_cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "warning",
                "-y",
                "-i", str(output),
            ]
            for trimmed_audio, _label in trimmed_sources:
                merge_cmd += ["-i", str(trimmed_audio)]

            has_existing_audio = self.has_audio_stream(output)
            if has_existing_audio or len(trimmed_sources) > 1:
                labels = ["[0:a:0]"] if has_existing_audio else []
                labels += [f"[{index}:a:0]" for index in range(1, len(trimmed_sources) + 1)]
                merge_cmd += [
                    "-filter_complex",
                    f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0[aout]",
                    "-map", "0:v:0",
                    "-map", "[aout]",
                ]
            else:
                merge_cmd += [
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                ]

            merge_cmd += [
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-t", f"{trim_duration:.3f}",
            ] + self.final_video_output_args(merged_output) + [str(merged_output)]
            merge_result = subprocess.run(
                merge_cmd,
                stdout=subprocess.DEVNULL,
                stderr=log_handle,
                creationflags=CREATE_NO_WINDOW,
            )
            if merge_result.returncode != 0:
                self.log(f"{context_label} audio merge failed; saved without separate audio. See FFmpeg log.")
                return []
            merged_output.replace(output)
            merged_labels = [label for _path, label in trimmed_sources]
            self.log(f"{context_label} audio merged: {', '.join(merged_labels)}.")
            return merged_labels
        finally:
            cleanup_paths.append(merged_output)
            for path in cleanup_paths:
                if path:
                    try:
                        path.unlink()
                    except OSError:
                        pass

    def video_bitrate_settings(self):
        try:
            target = int(self.config.get("video_bitrate_mbps", 35) or 35)
        except (TypeError, ValueError):
            target = 35
        try:
            maximum = int(self.config.get("max_bitrate_mbps", 50) or 50)
        except (TypeError, ValueError):
            maximum = 50
        target = max(1, min(300, target))
        maximum = max(target, min(500, maximum))
        buffer_size = max(maximum * 2, target * 2)
        return target, maximum, buffer_size

    def encoder_args(self, segmenting=False, live_capture=False, include_audio=True, separate_audio=False, backend_override=None):
        encoder = normalize_video_encoder(self.config.get("video_encoder", "auto"))
        if encoder == "auto":
            encoder = self.detect_encoder()

        backend = "gdigrab"
        if live_capture:
            try:
                backend = self.capture_backend(backend_override)
            except Exception:
                backend = "gdigrab"

        quality = int(self.config.get("quality", 23))
        bitrate_mode = str(self.config.get("bitrate_mode", "quality")).casefold()
        target_mbps, max_mbps, buffer_mbps = self.video_bitrate_settings()
        if encoder == "h264_nvenc":
            args = [
                "-c:v", "h264_nvenc",
                "-preset", "p5",
                "-bf", "0",
            ]
            if bitrate_mode == "target":
                args += [
                    "-rc", "vbr",
                    "-b:v", f"{target_mbps}M",
                    "-maxrate", f"{max_mbps}M",
                    "-bufsize", f"{buffer_mbps}M",
                ]
            else:
                args += [
                    "-rc", "vbr",
                    "-cq", str(quality),
                    "-b:v", "0",
                ]
            if not (live_capture and backend == "ddagrab"):
                args += ["-pix_fmt", "yuv420p"]
        elif encoder == "h264_amf":
            args = [
                "-vf", "hwdownload,format=bgra,format=yuv420p"
                if live_capture and backend == "ddagrab"
                else "format=yuv420p",
                "-c:v", "h264_amf",
                "-quality", "quality",
                "-bf", "0",
            ]
            if bitrate_mode == "target":
                args += [
                    "-rc", "vbr_peak",
                    "-b:v", f"{target_mbps}M",
                    "-maxrate", f"{max_mbps}M",
                    "-bufsize", f"{buffer_mbps}M",
                ]
            else:
                args += [
                    "-rc", "cqp",
                    "-qp_i", str(quality),
                    "-qp_p", str(quality),
                    "-qp_b", str(quality),
                ]
        elif encoder == "h264_qsv":
            args = [
                "-vf", "hwdownload,format=bgra,format=nv12"
                if live_capture and backend == "ddagrab"
                else "format=nv12",
                "-c:v", "h264_qsv",
                "-preset", "veryfast",
                "-bf", "0",
            ]
            if bitrate_mode == "target":
                args += [
                    "-b:v", f"{target_mbps}M",
                    "-maxrate", f"{max_mbps}M",
                    "-bufsize", f"{buffer_mbps}M",
                ]
            else:
                args += ["-global_quality", str(quality)]
        else:
            args = [
                "-vf", "hwdownload,format=bgra,format=yuv420p"
                if live_capture and backend == "ddagrab"
                else "format=yuv420p",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-bf", "0",
            ]
            if bitrate_mode == "target":
                args += [
                    "-b:v", f"{target_mbps}M",
                    "-maxrate", f"{max_mbps}M",
                    "-bufsize", f"{buffer_mbps}M",
                ]
            else:
                args += ["-crf", str(quality)]

        if segmenting:
            segment_seconds = int(self.config.get("segment_seconds", 4))
            fps = int(self.config.get("framerate", 60))
            keyint = max(1, fps * segment_seconds)
            args += ["-g", str(keyint)]
            if encoder == "h264_nvenc":
                args += ["-forced-idr", "1"]
            args += ["-force_key_frames", f"expr:gte(t,n_forced*{segment_seconds})"]

        if include_audio and self.direct_audio_input_devices(separate_audio=separate_audio):
            args += ["-c:a", "aac", "-b:a", "192k"]

        return args

    def final_video_output_args(self, output=None):
        args = ["-avoid_negative_ts", "make_zero"]
        if output is None or Path(output).suffix.casefold() in {".mp4", ".m4v", ".mov"}:
            args += ["-movflags", "+faststart"]
        return args

    def build_media_trim_command(
        self,
        input_path,
        output_path,
        start_seconds,
        end_seconds,
        accurate=False,
        include_audio=True,
        progress=False,
    ):
        ffmpeg = self.require_ffmpeg()
        start = max(0.0, float(start_seconds or 0))
        duration = max(0.01, float(end_seconds or 0) - start)
        command = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y"]
        if accurate and start > 0:
            command += ["-ss", f"{start:.3f}"]
        command += ["-i", str(input_path)]
        if not accurate and start > 0:
            command += ["-ss", f"{start:.3f}"]
        command += [
            "-t", f"{duration:.3f}",
            "-map", "0:v:0",
        ]
        if include_audio:
            command += ["-map", "0:a?"]
        command += ["-map_metadata", "0"]
        if accurate:
            command += self.encoder_args(
                segmenting=False,
                live_capture=False,
                include_audio=False,
                separate_audio=False,
            )
            if include_audio:
                command += ["-c:a", "aac", "-b:a", "192k"]
        else:
            command += ["-c", "copy"]
        command += self.final_video_output_args(output_path)
        if progress:
            command += ["-progress", "pipe:1", "-nostats"]
        command += [str(output_path)]
        return command

    def trim_media(
        self,
        input_path,
        start_seconds,
        end_seconds,
        output_path=None,
        accurate=False,
        progress_callback=None,
        cancel_event=None,
    ):
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(input_path)
        duration = self.probe_duration(input_path)
        if not duration or duration <= 0:
            raise RuntimeError("Could not read the clip duration.")
        start, end = clamp_trim_range(start_seconds, end_seconds, duration)
        output_path = Path(output_path) if output_path else trimmed_copy_path(input_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(
            f".{output_path.stem}.shadowclip-edit-{uuid.uuid4().hex}{output_path.suffix}"
        )
        log_path = self.logs_dir / timestamp_name("clip_edit", "log")
        selection_duration = end - start

        def run_export(use_accurate):
            command = self.build_media_trim_command(
                input_path,
                temp_path,
                start,
                end,
                accurate=use_accurate,
                include_audio=True,
                progress=True,
            )
            with log_path.open("a", encoding="utf-8") as log_handle:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=log_handle,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=CREATE_NO_WINDOW,
                )
                if process.stdout:
                    for raw_line in process.stdout:
                        if cancel_event and cancel_event.is_set():
                            process.terminate()
                            break
                        key, separator, value = raw_line.strip().partition("=")
                        if not separator or not progress_callback:
                            continue
                        if key in {"out_time_us", "out_time_ms"}:
                            try:
                                progress_callback(
                                    min(
                                        0.99,
                                        max(
                                            0.0,
                                            float(value) / 1_000_000.0 / selection_duration,
                                        ),
                                    )
                                )
                            except (TypeError, ValueError):
                                pass
                    process.stdout.close()
                return_code = process.wait()
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("Export cancelled.")
            return return_code

        try:
            return_code = run_export(bool(accurate))
            if return_code == 0 and not self.has_video_stream(temp_path):
                return_code = 1
            if return_code != 0 and not accurate:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                self.log(
                    "Fast clip edit was not supported by this file; "
                    "retrying frame-accurate export."
                )
                return_code = run_export(True)
            if return_code != 0 or not temp_path.exists():
                raise RuntimeError(f"Clip export failed. See log: {log_path}")
            replace_with_retries(temp_path, output_path)
            if self.last_clip_path and Path(self.last_clip_path) == input_path:
                self.last_clip_path = output_path
            if progress_callback:
                progress_callback(1.0)
            self.log(f"Trimmed clip saved: {output_path}")
            self.schedule_output_storage_cleanup()
            return output_path
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def output_dir(self):
        path = expand_path(self.config.get("output_dir", DEFAULT_CONFIG["output_dir"]))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def capture_folder_label(self, prefer_cached_game=False):
        if str(self.config.get("capture_mode", "")) == "window":
            title = str(self.config.get("window_title", "")).strip()
            hwnd = find_window_by_title(title)
            process_name = window_process_name(hwnd) if hwnd else ""
            label = friendly_application_name(process_name, title, "Game")
            self.remember_capture_label(label)
            return label

        label = sanitize_path_part(foreground_application_label(), "")
        if label:
            remembered = self.remember_capture_label(label)
            return remembered or label
        if prefer_cached_game:
            cached_label = self.cached_game_capture_label()
            if cached_label:
                return cached_label
        return "Desktop"

    def capture_output_dir(self, prefer_cached_game=False):
        root = self.output_dir()
        if not bool(self.config.get("organize_clips_by_game", True)):
            return root
        path = root / self.capture_folder_label(prefer_cached_game=prefer_cached_game)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def organize_saved_obs_media(self, output):
        output = Path(output)
        if not output.exists() or not bool(self.config.get("organize_clips_by_game", True)):
            return output
        target_dir = self.capture_output_dir(prefer_cached_game=True)
        try:
            if output.parent.resolve() == target_dir.resolve():
                return output
        except OSError:
            pass
        target = unique_destination_path(target_dir / output.name)
        last_error = None
        for attempt in range(20):
            try:
                shutil.move(str(output), str(target))
                self.log(f"OBS file moved to game folder: {target}")
                return target
            except OSError as exc:
                last_error = exc
                time.sleep(0.05 * min(attempt + 1, 8))
        if last_error:
            self.log(f"OBS file move to game folder failed: {last_error}")
        return output

    def make_output_path(self, prefix, container):
        return self.capture_output_dir() / timestamp_name(prefix, container)

    def latest_clip_path(self):
        if self.last_clip_path and Path(self.last_clip_path).exists():
            return Path(self.last_clip_path)
        candidates = [path for path in self.all_media_paths() if media_kind_for_path(path) == "replay"]
        if not candidates:
            return None
        return candidates[0]

    def all_media_paths(self):
        output_dir = self.output_dir()
        candidates = []
        try:
            for path in output_dir.rglob("*"):
                if not path.is_file() or path.suffix.casefold() not in MEDIA_EXTENSIONS:
                    continue
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    modified = 0
                candidates.append((modified, path))
        except OSError:
            return []
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [path for _modified, path in candidates]

    def recent_clip_paths(self, limit=12):
        candidates = [path for path in self.all_media_paths() if media_kind_for_path(path) == "replay"]
        return candidates[:max(0, int(limit or 0))]

    def recording_elapsed_seconds(self):
        if not self.record_proc or self.record_proc.poll() is not None or not self.recording_started_at:
            return None
        return time.time() - self.recording_started_at

    def current_recording_size(self):
        if not self.current_recording_path:
            return 0
        try:
            return Path(self.current_recording_path).stat().st_size
        except OSError:
            return 0

    def managed_output_files(self):
        current_recording = None
        if self.current_recording_path:
            try:
                current_recording = Path(self.current_recording_path).resolve()
            except OSError:
                current_recording = None
        files = []
        for path in self.all_media_paths():
            try:
                if current_recording and path.resolve() == current_recording:
                    continue
                stat = path.stat()
                files.append((path, stat.st_size, stat.st_mtime))
            except OSError:
                pass
        return files

    def cleanup_output_storage(self):
        try:
            max_storage_gb = float(self.config.get("max_storage_gb", 0) or 0)
        except (TypeError, ValueError):
            max_storage_gb = 0
        if max_storage_gb <= 0:
            return

        limit_bytes = int(max_storage_gb * 1024 * 1024 * 1024)
        files = self.managed_output_files()
        total_bytes = sum(size for _, size, _ in files)
        if total_bytes <= limit_bytes:
            return
        if len(files) <= 1:
            return

        deleted = 0
        freed = 0
        sorted_files = sorted(files, key=lambda item: item[2])
        protected_path = sorted_files[-1][0]
        for path, size, _ in sorted_files[:-1]:
            if total_bytes <= limit_bytes:
                break
            if path == protected_path:
                continue
            try:
                path.unlink()
                total_bytes -= size
                freed += size
                deleted += 1
            except OSError:
                pass
        if deleted:
            self.log(f"Storage cleanup removed {deleted} old file(s), freed {freed / (1024 ** 3):.2f} GB.")

    def schedule_output_storage_cleanup(self, force=False):
        try:
            max_storage_gb = float(self.config.get("max_storage_gb", 0) or 0)
        except (TypeError, ValueError):
            max_storage_gb = 0
        if max_storage_gb <= 0:
            return
        now = time.time()
        with self.storage_cleanup_lock:
            if self.storage_cleanup_running:
                return
            if not force and now - self.last_storage_cleanup_at < 30:
                return
            self.storage_cleanup_running = True

        def worker():
            try:
                self.cleanup_output_storage()
            finally:
                with self.storage_cleanup_lock:
                    self.last_storage_cleanup_at = time.time()
                    self.storage_cleanup_running = False

        threading.Thread(
            target=worker,
            daemon=True,
            name="ShadowClipStorageCleanup",
        ).start()

    def flush_log_handle(self, handle):
        try:
            if handle:
                handle.flush()
        except Exception:
            pass

    def ffmpeg_log_excerpt(self, log_path, max_chars=2400):
        try:
            path = Path(log_path)
            if not path.exists() or path.stat().st_size <= 0:
                return ""
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        excerpt = "\n".join(lines[-18:])
        if len(excerpt) > max_chars:
            excerpt = excerpt[-max_chars:]
        return excerpt

    def ffmpeg_log_has(self, log_path, needles):
        excerpt = self.ffmpeg_log_excerpt(log_path, max_chars=12000).casefold()
        return any(needle.casefold() in excerpt for needle in needles)

    def log_indicates_ddagrab_access_lost(self, log_path):
        return self.ffmpeg_log_has(
            log_path,
            [
                "acquirenextframe failed",
                "887a0026",
                "error during demuxing: generic error in an external library",
            ],
        )

    def log_indicates_hardware_encoder_failure(self, log_path):
        return self.ffmpeg_log_has(
            log_path,
            [
                "h264_nvenc",
                "nvenc",
                "nvidia",
                "h264_amf",
                "amf",
                "amd",
                "h264_qsv",
                "qsv",
                "quick sync",
                "quicksync",
                "onevpl",
                "mfx",
                "no capable devices found",
                "no device available",
                "unsupported device",
                "device creation failed",
                "openencodesessionex failed",
                "cannot load nvcuda",
                "cannot load nvencodeapi",
                "initializeencoder failed",
                "failed to create encoder",
                "error initializing output stream",
            ],
        ) and not self.log_indicates_ddagrab_access_lost(log_path)

    def describe_capture_failure(self, log_path):
        if self.log_indicates_ddagrab_access_lost(log_path):
            return (
                "DDA desktop duplication lost access to the display. "
                "This can happen when a game switches display mode or anti-cheat blocks the capture path."
            )
        excerpt = self.ffmpeg_log_excerpt(log_path)
        if excerpt:
            return excerpt.splitlines()[-1]
        return "No FFmpeg error text was written."

    def close_replay_log(self):
        if self.replay_log_handle:
            self.flush_log_handle(self.replay_log_handle)
            try:
                self.replay_log_handle.close()
            except Exception:
                pass
            self.replay_log_handle = None

    def close_record_log(self):
        if self.record_log_handle:
            self.flush_log_handle(self.record_log_handle)
            try:
                self.record_log_handle.close()
            except Exception:
                pass
            self.record_log_handle = None

    def start_recording(self):
        if self.record_proc and self.record_proc.poll() is None:
            self.log("Recording already running.")
            return

        backend_override = None
        backend = self.capture_backend()
        if backend == "obs":
            self.start_obs_recording()
            return

        ffmpeg = self.require_ffmpeg()
        container = self.config.get("container", "mkv")
        output = self.make_output_path("recording", container)
        log_path = self.logs_dir / timestamp_name("recording", "log")
        self.record_log_handle = log_path.open("w", encoding="utf-8")
        self.current_recording_path = output
        self.recording_active_backend = backend
        self.log(f"Recording capture backend: {backend}.")
        separate_audio = self.has_separate_audio_capture()
        include_live_audio = bool(self.direct_audio_input_devices(separate_audio=separate_audio))
        self.recording_uses_separate_audio = separate_audio
        self.recording_audio_owned = False
        if separate_audio:
            labels = ", ".join(source["label"] for source in self.separate_audio_sources())
            if any(thread.is_alive() for thread in self.audio_threads.values()):
                self.log(f"Recording will reuse existing audio buffer: {labels}.")
            else:
                self.start_audio_capture(clear_existing=True)
                self.recording_audio_owned = True
                self.log(f"Recording audio capture sources: {labels}.")

        cmd = (
            [ffmpeg, "-hide_banner", "-y"]
            + self.common_input_args(
                include_audio=include_live_audio,
                separate_audio=separate_audio,
                backend_override=backend_override,
            )
            + self.output_map_args(include_audio=include_live_audio, separate_audio=separate_audio)
            + self.encoder_args(
                segmenting=False,
                live_capture=True,
                include_audio=include_live_audio,
                separate_audio=separate_audio,
                backend_override=backend_override,
            )
            + [str(output)]
        )
        self.recording_started_at = time.time()
        self.record_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self.record_log_handle,
            creationflags=CREATE_NO_WINDOW,
        )
        if self._retry_with_cpu_if_hardware_encoder_fails("recording", log_path):
            cmd = (
                [ffmpeg, "-hide_banner", "-y"]
                + self.common_input_args(
                    include_audio=include_live_audio,
                    separate_audio=separate_audio,
                    backend_override=backend_override,
                )
                + self.output_map_args(include_audio=include_live_audio, separate_audio=separate_audio)
                + self.encoder_args(
                    segmenting=False,
                    live_capture=True,
                    include_audio=include_live_audio,
                    separate_audio=separate_audio,
                    backend_override=backend_override,
                )
                + [str(output)]
            )
            self.recording_started_at = time.time()
            self.record_proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self.record_log_handle,
                creationflags=CREATE_NO_WINDOW,
            )
        if self.record_proc and self.record_proc.poll() is not None:
            fallback = self.capture_backend_fallback(backend)
            if fallback:
                self.flush_log_handle(self.record_log_handle)
                self.log(f"Recording failed with {backend}; retrying with {fallback} capture backend.")
                backend_override = fallback
                cmd = (
                    [ffmpeg, "-hide_banner", "-y"]
                    + self.common_input_args(
                        include_audio=include_live_audio,
                        separate_audio=separate_audio,
                        backend_override=backend_override,
                    )
                    + self.output_map_args(include_audio=include_live_audio, separate_audio=separate_audio)
                    + self.encoder_args(
                        segmenting=False,
                        live_capture=True,
                        include_audio=include_live_audio,
                        separate_audio=separate_audio,
                        backend_override=backend_override,
                    )
                    + [str(output)]
                )
                self.recording_started_at = time.time()
                self.record_proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=self.record_log_handle,
                    creationflags=CREATE_NO_WINDOW,
                )
                time.sleep(1.2)
        if not self.record_proc or self.record_proc.poll() is not None:
            self.flush_log_handle(self.record_log_handle)
            reason = self.describe_capture_failure(log_path)
            self.record_proc = None
            self.current_recording_path = None
            self.recording_active_backend = None
            if self.recording_audio_owned:
                self.stop_audio_capture()
            self.recording_uses_separate_audio = False
            self.recording_audio_owned = False
            self.recording_started_at = None
            self.close_record_log()
            raise RuntimeError(f"FFmpeg exited while starting recording. {reason} See log: {log_path}")
        if separate_audio and not include_live_audio:
            self.log("Recording video capture is running without live FFmpeg audio inputs.")
        self.log(f"Recording started: {output}")

    def stop_recording(self):
        if not self.record_proc or self.record_proc.poll() is not None:
            self.log("No recording running.")
            return
        if self.recording_active_backend == "obs":
            self.stop_obs_recording()
            return
        output = Path(self.current_recording_path) if self.current_recording_path else None
        started_at = self.recording_started_at
        uses_separate_audio = self.recording_uses_separate_audio
        self._stop_process(self.record_proc, "recording")
        stopped_at = time.time()
        self.record_proc = None
        replay_still_running = bool(self.replay_proc and self.replay_proc.poll() is None)
        if uses_separate_audio and output and output.exists():
            if not replay_still_running:
                self.stop_audio_capture()
            try:
                duration = self.probe_duration(output) or max(stopped_at - (started_at or stopped_at), 0)
                if duration > 0:
                    wall_duration = max(stopped_at - (started_at or stopped_at), 0)
                    clip_start = started_at or max(stopped_at - duration, 0)
                    self.log(
                        f"Recording timing: video_duration={duration:.3f}s, "
                        f"wall_duration={wall_duration:.3f}s."
                    )
                    self.add_separate_audio(
                        self.require_ffmpeg(),
                        output,
                        duration,
                        clip_start,
                        clip_start + duration,
                        self.record_log_handle,
                        context_label="Recording",
                    )
                if self.has_audio_stream(output):
                    self.log("Recording audio stream OK.")
                else:
                    self.log("Recording saved without audio stream. See recording FFmpeg log.")
            except Exception as exc:
                self.log(f"Recording audio merge failed: {exc}")
        self.recording_started_at = None
        self.current_recording_path = None
        self.recording_active_backend = None
        self.recording_uses_separate_audio = False
        self.recording_audio_owned = False
        self.close_record_log()
        self.cleanup_segments()
        self.schedule_output_storage_cleanup()

    def start_replay(self, preserve_buffer=False, from_watchdog=False):
        if self.replay_proc and self.replay_proc.poll() is None:
            self.log("Replay buffer already running.")
            return

        backend = self.capture_backend(self.replay_backend_override)
        if backend == "obs":
            self.start_obs_replay(preserve_buffer=preserve_buffer, from_watchdog=from_watchdog)
            return

        ffmpeg = self.require_ffmpeg()
        self.replay_dir.mkdir(parents=True, exist_ok=True)
        if not preserve_buffer:
            self.last_clip_saved_at = 0.0
            self.replay_backend_override = None
            self.replay_restart_count = 0
            for segment in self.replay_dir.glob("segment_*.mkv"):
                try:
                    segment.unlink()
                except OSError:
                    pass

        segment_seconds = int(self.config.get("segment_seconds", 4))
        pattern = str(self.replay_dir / "segment_%Y-%m-%d_%H-%M-%S.mkv")
        log_path = self.logs_dir / timestamp_name("replay", "log")
        self.replay_log_handle = log_path.open("w", encoding="utf-8")
        self.replay_current_log_path = log_path
        separate_audio = self.has_separate_audio_capture()
        include_live_audio = bool(self.direct_audio_input_devices(separate_audio=separate_audio))
        self.replay_active_backend = backend
        self.log(f"Replay capture backend: {backend}.")

        cmd = (
            [ffmpeg, "-hide_banner", "-y"]
            + self.common_input_args(
                include_audio=include_live_audio,
                separate_audio=separate_audio,
                backend_override=self.replay_backend_override,
            )
            + self.output_map_args(include_audio=include_live_audio, separate_audio=separate_audio)
            + self.encoder_args(
                segmenting=True,
                live_capture=True,
                include_audio=include_live_audio,
                separate_audio=separate_audio,
                backend_override=self.replay_backend_override,
            )
            + [
                "-f", "segment",
                "-segment_time", str(segment_seconds),
                "-reset_timestamps", "1",
                "-strftime", "1",
                pattern,
            ]
        )
        self.replay_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self.replay_log_handle,
            creationflags=CREATE_NO_WINDOW,
        )
        if self._retry_with_cpu_if_hardware_encoder_fails("replay", log_path):
            cmd = (
                [ffmpeg, "-hide_banner", "-y"]
                + self.common_input_args(
                    include_audio=include_live_audio,
                    separate_audio=separate_audio,
                    backend_override=self.replay_backend_override,
                )
                + self.output_map_args(include_audio=include_live_audio, separate_audio=separate_audio)
                + self.encoder_args(
                    segmenting=True,
                    live_capture=True,
                    include_audio=include_live_audio,
                    separate_audio=separate_audio,
                    backend_override=self.replay_backend_override,
                )
                + [
                    "-f", "segment",
                    "-segment_time", str(segment_seconds),
                    "-reset_timestamps", "1",
                    "-strftime", "1",
                    pattern,
                ]
            )
            self.replay_proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self.replay_log_handle,
                creationflags=CREATE_NO_WINDOW,
            )
        if self.replay_proc and self.replay_proc.poll() is not None:
            fallback = self.capture_backend_fallback(backend)
            if fallback:
                self.flush_log_handle(self.replay_log_handle)
                self.close_replay_log()
                self.replay_proc = None
                self.replay_backend_override = fallback
                self.replay_restart_count += 1
                self.log(f"Replay failed with {backend}; retrying with {fallback} capture backend.")
                return self.start_replay(preserve_buffer=True, from_watchdog=from_watchdog)
            self.flush_log_handle(self.replay_log_handle)
            reason = self.describe_capture_failure(log_path)
            self.replay_proc = None
            self.close_replay_log()
            raise RuntimeError(f"FFmpeg exited while starting replay. {reason} See log: {log_path}")
        self.replay_should_restart = True
        self.stop_cleanup.clear()
        if not self.cleanup_thread or not self.cleanup_thread.is_alive():
            self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
            self.cleanup_thread.start()
        self.start_audio_capture(clear_existing=not preserve_buffer)
        if separate_audio and not include_live_audio:
            self.log("Replay video capture is running without live FFmpeg audio inputs.")
        elif separate_audio:
            labels = ", ".join(source["label"] for source in self.separate_audio_sources())
            self.log(f"Replay will merge separate audio sources later: {labels}.")
        if from_watchdog:
            self.log("Replay buffer restarted.")
        else:
            self.log("Replay buffer started.")
        self.start_replay_watchdog(self.replay_proc, log_path, backend)

    def start_replay_watchdog(self, proc, log_path, backend):
        if not bool(self.config.get("replay_auto_restart", True)):
            return
        thread = threading.Thread(
            target=self.replay_watchdog_loop,
            args=(proc, log_path, backend),
            daemon=True,
        )
        self.replay_watchdog_thread = thread
        thread.start()

    def replay_watchdog_loop(self, proc, log_path, backend):
        while self.replay_should_restart and self.replay_proc is proc:
            time.sleep(1.0)
            if proc.poll() is None:
                continue
            if not self.replay_should_restart or self.replay_proc is not proc:
                return

            self.flush_log_handle(self.replay_log_handle)
            exit_code = proc.returncode
            reason = self.describe_capture_failure(log_path)
            self.log(f"Replay FFmpeg exited unexpectedly (code {exit_code}). {reason}")

            fallback = self.capture_backend_fallback(backend)
            if fallback and self.log_indicates_ddagrab_access_lost(log_path):
                self.replay_backend_override = fallback
                self.log(
                    "Replay auto-restart: DDA lost access, switching to GDI desktop capture. "
                    "For anti-cheat games, borderless fullscreen is usually more reliable than exclusive fullscreen."
                )

            self.close_replay_log()
            self.replay_proc = None

            try:
                max_restarts = int(self.config.get("replay_max_restarts", 3) or 3)
            except (TypeError, ValueError):
                max_restarts = 3
            if self.replay_restart_count >= max_restarts:
                self.replay_should_restart = False
                self.log("Replay auto-restart stopped after repeated FFmpeg exits.")
                return

            self.replay_restart_count += 1
            time.sleep(1.2)
            try:
                self.start_replay(preserve_buffer=True, from_watchdog=True)
            except Exception as exc:
                self.replay_should_restart = False
                self.replay_proc = None
                self.log(f"Replay auto-restart failed: {exc}")
            return

    def restart_replay_capture(self, reason="", backend_override=None):
        if not self.replay_proc or self.replay_proc.poll() is not None:
            return False
        if self.replay_active_backend == "obs":
            self.replay_should_restart = False
            if reason:
                self.log(f"Replay capture restart: {reason}")
            self.stop_obs_replay()
            if backend_override:
                self.replay_backend_override = backend_override
            self.replay_restart_count = 0
            self.start_replay(preserve_buffer=True, from_watchdog=True)
            return True
        self.replay_should_restart = False
        proc = self.replay_proc
        self._stop_process(proc, "replay capture")
        self.replay_proc = None
        self.close_replay_log()
        if backend_override:
            self.replay_backend_override = backend_override
        self.replay_restart_count = 0
        if reason:
            self.log(f"Replay capture restart: {reason}")
        self.start_replay(preserve_buffer=True, from_watchdog=True)
        return True

    def stop_replay(self):
        if not self.replay_proc or self.replay_proc.poll() is not None:
            self.replay_should_restart = False
            self.log("Replay buffer is not running.")
            return
        if self.replay_active_backend == "obs":
            self.stop_obs_replay()
            return
        self.replay_should_restart = False
        self.stop_cleanup.set()
        recording_needs_audio = bool(
            self.record_proc
            and self.record_proc.poll() is None
            and self.recording_uses_separate_audio
        )
        if not recording_needs_audio:
            self.stop_audio_capture()
        self._stop_process(self.replay_proc, "replay")
        self.replay_proc = None
        self.replay_active_backend = None
        self.close_replay_log()

    def toggle_replay(self):
        if self.replay_proc and self.replay_proc.poll() is None:
            self.stop_replay()
        else:
            self.start_replay()

    def toggle_recording(self):
        if self.record_proc and self.record_proc.poll() is None:
            self.stop_recording()
        else:
            self.start_recording()

    def save_clip_async(self):
        thread = threading.Thread(target=self.save_clip, daemon=True)
        thread.start()

    def save_clip(self):
        if not self.replay_proc or self.replay_proc.poll() is not None:
            self.log("Start replay buffer first.")
            return
        try:
            desired_backend = self.capture_backend(self.replay_backend_override)
        except Exception:
            desired_backend = None
        if desired_backend and self.replay_active_backend and desired_backend != self.replay_active_backend:
            self.log(
                f"Replay is running with {self.replay_active_backend}; "
                f"stop and start replay to use selected {desired_backend} backend."
            )
        if not self.save_lock.acquire(blocking=False):
            self.log("Clip save already running.")
            return

        try:
            if self.replay_active_backend == "obs":
                try:
                    self.save_obs_clip()
                except Exception as exc:
                    self.log(f"OBS clip save failed: {exc}")
                return

            ffmpeg = self.require_ffmpeg()
            clip_seconds = int(self.config.get("clip_seconds", 60))
            segment_seconds = int(self.config.get("segment_seconds", 4))
            now = time.time()
            reset_after_clip = bool(self.config.get("reset_replay_after_clip", True))
            target_clip_seconds = float(clip_seconds)
            clip_label = f"{clip_seconds}s target"
            if reset_after_clip and self.last_clip_saved_at:
                elapsed = now - self.last_clip_saved_at
                if elapsed < 1:
                    self.log("Replay reset active: not enough new replay time yet.")
                    return
                target_clip_seconds = min(float(clip_seconds), elapsed)
                clip_label = f"{target_clip_seconds:.1f}s new replay"

            cutoff = now - target_clip_seconds - segment_seconds
            if reset_after_clip and self.last_clip_saved_at:
                cutoff = max(cutoff, self.last_clip_saved_at - segment_seconds)
            all_segments = sorted(self.replay_dir.glob("segment_*.mkv"), key=lambda p: p.stat().st_mtime)
            complete_segments = all_segments[:-1] if len(all_segments) > 1 else []
            selected = [p for p in complete_segments if p.stat().st_mtime >= cutoff]

            if not selected:
                self.log("No completed replay segments yet. Wait a few seconds and try again.")
                return
            latest_finalized_at = max(p.stat().st_mtime for p in selected)
            if reset_after_clip and self.last_clip_saved_at:
                finalized_new_seconds = latest_finalized_at - self.last_clip_saved_at
                if finalized_new_seconds < 1:
                    self.log("No finalized new replay time is ready yet. Try again in a moment.")
                    return
                target_clip_seconds = min(float(clip_seconds), finalized_new_seconds)
                clip_label = f"{target_clip_seconds:.1f}s new replay"

            output = self.make_output_path("clip", self.config.get("container", "mkv"))
            joined = self.runtime_dir / timestamp_name("clip_joined", "mkv")
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
                list_path = Path(handle.name)
                for segment in selected:
                    safe_path = segment.resolve().as_posix().replace("'", "'\\''")
                    handle.write(f"file '{safe_path}'\n")

            log_path = self.logs_dir / timestamp_name("clip", "log")
            with log_path.open("w", encoding="utf-8") as log_handle:
                concat_result = subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel", "warning",
                        "-y",
                        "-safe", "0",
                        "-f", "concat",
                        "-i", str(list_path),
                        "-c", "copy",
                        str(joined),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=log_handle,
                    creationflags=CREATE_NO_WINDOW,
                )
                result = concat_result
                if concat_result.returncode == 0:
                    duration = self.probe_duration(joined)
                    if duration is not None:
                        trim_duration = min(target_clip_seconds, duration)
                    else:
                        trim_duration = target_clip_seconds
                    if trim_duration < 1:
                        self.log("No finalized replay time is ready yet. Try again in a moment.")
                        try:
                            output.unlink()
                        except OSError:
                            pass
                        try:
                            list_path.unlink()
                        except OSError:
                            pass
                        try:
                            joined.unlink()
                        except OSError:
                            pass
                        return
                    if duration is not None and duration + 0.25 < target_clip_seconds:
                        clip_label = f"{duration:.1f}s finalized replay"
                    seek_start = max((duration or 0) - trim_duration, 0)
                    separate_audio = self.has_separate_audio_capture()
                    include_live_audio = bool(self.direct_audio_input_devices(separate_audio=separate_audio))
                    use_fast_trim = seek_start <= 0.01
                    trim_cmd = self.build_media_trim_command(
                        joined,
                        output,
                        seek_start,
                        seek_start + trim_duration,
                        accurate=not use_fast_trim,
                        include_audio=include_live_audio,
                    )
                    result = subprocess.run(
                        trim_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=log_handle,
                        creationflags=CREATE_NO_WINDOW,
                    )
                    if (
                        use_fast_trim
                        and result.returncode == 0
                        and not self.has_video_stream(output)
                    ):
                        try:
                            output.unlink()
                        except OSError:
                            pass
                        result = subprocess.CompletedProcess(trim_cmd, 1)
                    if result.returncode != 0 and use_fast_trim:
                        self.log(
                            "Fast clip save was not supported by this segment; "
                            "retrying with frame-accurate encoding."
                        )
                        try:
                            output.unlink()
                        except OSError:
                            pass
                        trim_cmd = self.build_media_trim_command(
                            joined,
                            output,
                            seek_start,
                            seek_start + trim_duration,
                            accurate=True,
                            include_audio=include_live_audio,
                        )
                        result = subprocess.run(
                            trim_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=log_handle,
                            creationflags=CREATE_NO_WINDOW,
                        )
                    if (
                        result.returncode != 0
                        and self.config.get("video_encoder") == "auto"
                        and self.encoder_cache in HARDWARE_VIDEO_ENCODERS
                    ):
                        failed_encoder = self.encoder_cache
                        self.encoder_cache = "libx264"
                        self.log(
                            f"{video_encoder_label(failed_encoder)} failed during clip trim; "
                            "retrying with libx264."
                        )
                        trim_cmd = self.build_media_trim_command(
                            joined,
                            output,
                            seek_start,
                            seek_start + trim_duration,
                            accurate=True,
                            include_audio=include_live_audio,
                        )
                        result = subprocess.run(
                            trim_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=log_handle,
                            creationflags=CREATE_NO_WINDOW,
                        )
                    if result.returncode == 0:
                        first_video_start = parse_replay_segment_start(selected[0])
                        if first_video_start is None:
                            first_video_start = selected[0].stat().st_mtime - (duration or target_clip_seconds)
                        clip_start_wall_time = first_video_start + seek_start
                        clip_end_wall_time = clip_start_wall_time + trim_duration
                        if separate_audio:
                            self.add_separate_audio(
                                ffmpeg,
                                output,
                                trim_duration,
                                clip_start_wall_time,
                                clip_end_wall_time,
                                log_handle,
                                context_label="Clip",
                            )
                        if separate_audio or include_live_audio:
                            if self.has_audio_stream(output):
                                self.log("Clip audio stream OK.")
                            else:
                                self.log(f"Clip saved without audio stream. See log: {log_path}")
            try:
                list_path.unlink()
            except OSError:
                pass
            try:
                joined.unlink()
            except OSError:
                pass

            if result.returncode == 0:
                self.last_clip_path = output
                self.log(f"Clip saved ({clip_label}): {output}")
                self.schedule_output_storage_cleanup()
                if reset_after_clip:
                    self.last_clip_saved_at = now
                    self.cleanup_segments()
                    self.log("Replay window reset; the next clip will save only new replay time.")
            else:
                self.log(f"Clip save failed. See log: {log_path}")
        finally:
            self.save_lock.release()

    def _cleanup_loop(self):
        while not self.stop_cleanup.wait(5):
            self.cleanup_segments()

    def cleanup_segments(self):
        keep_seconds = int(self.config.get("clip_seconds", 60)) + int(self.config.get("segment_seconds", 4)) * 3
        cutoff = time.time() - keep_seconds
        audio_cutoff = cutoff
        if self.recording_started_at:
            audio_cutoff = min(audio_cutoff, max(self.recording_started_at - 5.0, 0))
        for segment in self.replay_dir.glob("segment_*.mkv"):
            try:
                if segment.stat().st_mtime < cutoff:
                    segment.unlink()
            except OSError:
                pass
        if self.audio_base_dir.exists():
            for segment in self.audio_base_dir.glob("*/*.wav"):
                parsed = parse_audio_segment_times(segment)
                try:
                    segment_end = parsed[1] if parsed else segment.stat().st_mtime
                    if segment_end < audio_cutoff:
                        segment.unlink()
                except OSError:
                    pass

    def _stop_process(self, proc, label):
        if proc.poll() is not None:
            return
        try:
            if proc.stdin:
                proc.stdin.write(b"q\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(timeout=8)
            self.log(f"Stopped {label}.")
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
            self.log(f"Forced {label} to stop.")

    def _retry_with_cpu_if_hardware_encoder_fails(self, process_name, log_path=None):
        if self.config.get("video_encoder") != "auto" or self.encoder_cache not in HARDWARE_VIDEO_ENCODERS:
            return False
        time.sleep(1.2)
        proc = self.record_proc if process_name == "recording" else self.replay_proc
        if proc and proc.poll() is not None:
            if log_path:
                self.flush_log_handle(self.record_log_handle if process_name == "recording" else self.replay_log_handle)
                if not self.log_indicates_hardware_encoder_failure(log_path):
                    return False
            failed_encoder = self.encoder_cache
            self.encoder_cache = "libx264"
            self.log(f"{video_encoder_label(failed_encoder)} failed to start for {process_name}; retrying with libx264.")
            return True
        return False

    def stop_all(self):
        self.replay_should_restart = False
        self.stop_cleanup.set()
        if self.replay_proc and self.replay_proc.poll() is None:
            self.stop_replay()
        if self.record_proc and self.record_proc.poll() is None:
            self.stop_recording()
        self.stop_audio_capture()
        self.stop_obs_runtime()


class ShadowClipApp:
    def __init__(self, root, start_minimized=False):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION.split('-', 1)[0]}")
        try:
            icon_path = resource_path(APP_ICON_NAME)
            if icon_path.exists():
                self.root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass
        self.root.minsize(960, 720)
        self.config = load_config()
        self.manager = FfmpegManager(self.config, self.threadsafe_log)
        self.log_queue = queue.Queue()
        self.recent_log_lines = []
        self.icon_images = {}
        self.home_last_clip_preview_image = None
        self.home_last_clip_preview_signature = None
        self.home_last_clip_preview_pending = None
        self.home_last_clip_preview_request_id = 0
        self.clip_library_items = []
        self.clip_library_filtered = []
        self.clip_library_scan_id = 0
        self.clip_library_scan_running = False
        self.clip_library_refresh_pending = False
        self.clip_library_last_scan_at = 0.0
        self.clip_library_render_limit = 24
        self.clip_library_columns = 0
        self.clip_library_render_after_id = None
        self.clip_gallery_thumbnail_queue = queue.Queue()
        self.clip_gallery_thumbnail_pending = set()
        self.clip_gallery_thumbnail_worker = None
        self.clip_gallery_thumbnail_images = {}
        self.clip_gallery_card_canvases = {}
        self.clip_gallery_metadata_labels = {}
        self.clip_gallery_metadata_cache = {}
        self.settings_dirty = False
        self.settings_dirty_tracking = False
        self.settings_state_labels = []
        self.settings_save_buttons = []
        self.monitors = enum_monitors()
        self.windows = []
        self.audio_devices = []
        self.hotkey_vars = {}
        config_hotkeys = self.config.get("hotkeys", DEFAULT_CONFIG["hotkeys"])
        for action, _label in HOTKEY_ACTIONS:
            value = config_hotkeys.get(action, DEFAULT_CONFIG["hotkeys"][action])
            try:
                value = parse_hotkey_text(value)[2]
            except ValueError:
                value = DEFAULT_CONFIG["hotkeys"][action]
            self.hotkey_vars[action] = tk.StringVar(value=value)
        self.hotkeys = HotkeyThread(self.dispatch_hotkey, self.threadsafe_log, self.collect_hotkey_config())
        self.tray = TrayIconThread(self.dispatch_tray_action, self.threadsafe_log, self.tray_state)
        self.is_quitting = False
        self.tray_hint_shown = False
        self.output_picker_running = False
        self.ffmpeg_picker_running = False
        self.obs_picker_running = False
        self.overlay = None
        self.overlay_bounds = None
        self.overlay_buttons = {}
        self.overlay_home = None
        self.overlay_settings = None
        self.overlay_gallery = None
        self.overlay_gallery_list = None
        self.overlay_gallery_canvas = None
        self.overlay_gallery_count_label = None
        self.overlay_mode = "home"
        self.overlay_visible = False
        self.overlay_click_through = False
        self.event_toast = None
        self.event_toast_after_ids = []
        self.recording_indicator = None
        self.recording_indicator_state = None
        self.noactivate_window_procs = {}
        self.fullscreen_capture_signature = None
        self.fullscreen_capture_pending_signature = None
        self.fullscreen_capture_restart_after_id = None
        self.fullscreen_capture_last_restart_at = 0.0
        self.fullscreen_capture_last_restart_signature = None
        self.fullscreen_capture_warning_keys = set()
        self.update_check_running = False
        self.update_download_running = False
        self.health_check_running = False
        self.health_check_results_window = None
        self.health_repair_pending_output = False
        self.debug_report_running = False
        self.setup_wizard = None
        self.setup_wizard_step = 0
        self.setup_wizard_auto = False
        self.setup_wizard_scan_running = False
        self.setup_wizard_scan_result = {}
        self.setup_wizard_vars = {}
        self.capture_self_test_running = False
        self.capture_self_test_window = None
        self.capture_self_test_results_window = None
        self.capture_self_test_status_label = None
        self.capture_self_test_progress = None
        self.capture_self_test_last_result = None
        self.pending_update = None
        self.updating_auto_video_bitrate = False
        self.updating_auto_replay_ram = False
        self.last_applied_game_profile_key = ""

        self.vars = {
            "ffmpeg_path": tk.StringVar(value=self.config.get("ffmpeg_path", "")),
            "obs_path": tk.StringVar(value=self.config.get("obs_path", "")),
            "output_dir": tk.StringVar(value=self.config.get("output_dir", DEFAULT_CONFIG["output_dir"])),
            "capture_mode": tk.StringVar(value=self.config.get("capture_mode", "desktop_all")),
            "capture_backend": tk.StringVar(value=self.config.get("capture_backend", DEFAULT_CONFIG["capture_backend"])),
            "obs_minecraft_capture_mode": tk.StringVar(value=self.config.get("obs_minecraft_capture_mode", DEFAULT_CONFIG["obs_minecraft_capture_mode"])),
            "capture_desktop_overlays": tk.BooleanVar(value=bool(self.config.get("capture_desktop_overlays", DEFAULT_CONFIG["capture_desktop_overlays"]))),
            "monitor_index": tk.IntVar(value=int(self.config.get("monitor_index", 0))),
            "window_title": tk.StringVar(value=self.config.get("window_title", "")),
            "framerate": tk.IntVar(value=int(self.config.get("framerate", 60))),
            "clip_seconds": tk.IntVar(value=int(self.config.get("clip_seconds", 60))),
            "segment_seconds": tk.IntVar(value=int(self.config.get("segment_seconds", 4))),
            "video_encoder": tk.StringVar(value=self.config.get("video_encoder", "auto")),
            "quality": tk.IntVar(value=int(self.config.get("quality", 23))),
            "auto_video_bitrate": tk.BooleanVar(value=bool(self.config.get("auto_video_bitrate", DEFAULT_CONFIG["auto_video_bitrate"]))),
            "auto_bitrate_preset": tk.StringVar(value=normalize_auto_bitrate_preset(self.config.get("auto_bitrate_preset", DEFAULT_CONFIG["auto_bitrate_preset"]))),
            "bitrate_mode": tk.StringVar(value=self.config.get("bitrate_mode", DEFAULT_CONFIG["bitrate_mode"])),
            "video_bitrate_mbps": tk.IntVar(value=int(self.config.get("video_bitrate_mbps", 35))),
            "max_bitrate_mbps": tk.IntVar(value=int(self.config.get("max_bitrate_mbps", 50))),
            "obs_replay_ram_auto": tk.BooleanVar(value=bool(self.config.get("obs_replay_ram_auto", DEFAULT_CONFIG["obs_replay_ram_auto"]))),
            "obs_replay_buffer_mb": tk.IntVar(value=int(self.config.get("obs_replay_buffer_mb", DEFAULT_CONFIG["obs_replay_buffer_mb"]))),
            "audio_mode": tk.StringVar(value=self.config.get("audio_mode", "none")),
            "audio_device": tk.StringVar(value=self.config.get("audio_device", "")),
            "mic_enabled": tk.BooleanVar(value=bool(self.config.get("mic_enabled", False))),
            "mic_device": tk.StringVar(value=self.config.get("mic_device") or self.config.get("audio_device", "")),
            "desktop_audio_enabled": tk.BooleanVar(value=bool(self.config.get("desktop_audio_enabled", False))),
            "desktop_audio_backend": tk.StringVar(value=self.config.get("desktop_audio_backend", "wasapi")),
            "desktop_audio_device": tk.StringVar(value=self.config.get("desktop_audio_device", "")),
            "audio_offset_ms": tk.IntVar(value=int(self.config.get("audio_offset_ms", 0))),
            "recording_audio_offset_ms": tk.IntVar(value=int(self.config.get("recording_audio_offset_ms", DEFAULT_CONFIG["recording_audio_offset_ms"]))),
            "start_with_windows": tk.BooleanVar(value=bool(self.config.get("start_with_windows", False))),
            "auto_start_replay": tk.BooleanVar(value=bool(self.config.get("auto_start_replay", False))),
            "use_game_profiles": tk.BooleanVar(value=bool(self.config.get("use_game_profiles", DEFAULT_CONFIG["use_game_profiles"]))),
            "organize_clips_by_game": tk.BooleanVar(value=bool(self.config.get("organize_clips_by_game", True))),
            "max_storage_gb": tk.DoubleVar(value=float(self.config.get("max_storage_gb", 0) or 0)),
            "container": tk.StringVar(value=self.config.get("container", "mkv")),
            "reset_replay_after_clip": tk.BooleanVar(value=bool(self.config.get("reset_replay_after_clip", True))),
            "toast_duration_ms": tk.IntVar(value=int(self.config.get("toast_duration_ms", 2600))),
            "toast_position": tk.StringVar(value=self.config.get("toast_position", "top_right")),
            "gallery_limit": tk.IntVar(value=int(self.config.get("gallery_limit", 12))),
            "hide_overlay_after_clip": tk.BooleanVar(value=bool(self.config.get("hide_overlay_after_clip", True))),
            "recording_indicator_enabled": tk.BooleanVar(value=bool(self.config.get("recording_indicator_enabled", True))),
            "fullscreen_safe_hud": tk.BooleanVar(value=bool(self.config.get("fullscreen_safe_hud", True))),
            "event_sounds_enabled": tk.BooleanVar(value=bool(self.config.get("event_sounds_enabled", True))),
            "check_updates_on_start": tk.BooleanVar(value=bool(self.config.get("check_updates_on_start", True))),
        }
        self.clip_search_var = tk.StringVar(value="")
        self.clip_game_filter_var = tk.StringVar(value="All games/apps")
        self.clip_kind_filter_var = tk.StringVar(value="All media")
        self.clip_sort_var = tk.StringVar(value="Newest first")
        self.status_var = tk.StringVar(value="Ready")
        self.replay_status_var = tk.StringVar(value=ui_text("replay", "Replay: Idle"))
        self.recording_status_var = tk.StringVar(value=ui_text("record", "Recording: Idle"))
        self.audio_status_var = tk.StringVar(value=ui_text("audio", "Audio: Off"))
        self.source_status_var = tk.StringVar(value=ui_text("source", "Source: Desktop"))
        self.storage_status_var = tk.StringVar(value=ui_text("storage", "Storage: Not limited"))

        self.build_ui()
        self.root.after(50, self.apply_dark_titlebar)
        self.bind_status_traces()
        self.sync_auto_video_bitrate(force=True)
        self.sync_auto_obs_replay_buffer(force=True)
        self.root.after(700, self.enable_settings_dirty_tracking)
        self.refresh_windows()
        self.refresh_monitors()
        self.root.after(100, self.drain_log_queue)
        self.root.after(1000, self.tick_recording_timer)
        self.root.after(2400, self.monitor_fullscreen_capture_context)
        self.hotkeys.start()
        self.tray.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.threadsafe_log(f"Ready. {APP_NAME} {APP_VERSION}. Set FFmpeg path or run Install-FFmpeg.ps1 first.")
        self.update_tray_status()
        setup_completed = bool(self.config.get("setup_completed", True))
        if not setup_completed and not start_minimized:
            self.root.after(900, lambda: self.show_setup_wizard(auto=True))
        if setup_completed and bool(self.config.get("auto_start_replay", False)):
            self.root.after(1200, self.auto_start_replay)
        if setup_completed and bool(self.config.get("check_updates_on_start", True)):
            self.root.after(3200, lambda: self.check_for_updates(silent=True))
        if start_minimized:
            self.root.after(600, lambda: self.hide_window(show_hint=False))

    def build_legacy_ui(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        style = ttk.Style(root)
        style.configure("Status.TLabel", padding=(10, 6), anchor="center", font=("Segoe UI Symbol", 9))
        style.configure("Toolbar.TButton", padding=(10, 5), font=("Segoe UI Symbol", 9))

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=f"{ui_text('app', APP_NAME)} {APP_VERSION}", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.status_var, anchor="e").grid(row=0, column=1, sticky="e")

        status_grid = ttk.Frame(root)
        status_grid.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        for col in range(5):
            status_grid.columnconfigure(col, weight=1, uniform="status")
        ttk.Label(status_grid, textvariable=self.replay_status_var, style="Status.TLabel", relief="groove").grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Label(status_grid, textvariable=self.recording_status_var, style="Status.TLabel", relief="groove").grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(status_grid, textvariable=self.audio_status_var, style="Status.TLabel", relief="groove").grid(row=0, column=2, sticky="ew", padx=6)
        ttk.Label(status_grid, textvariable=self.source_status_var, style="Status.TLabel", relief="groove").grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Label(status_grid, textvariable=self.storage_status_var, style="Status.TLabel", relief="groove").grid(row=0, column=4, sticky="ew", padx=(6, 0))

        controls = ttk.LabelFrame(root, text=ui_text("settings", "Controls"))
        controls.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))
        for col in range(6):
            controls.columnconfigure(col, weight=1)
        self.replay_button = ttk.Button(controls, text=ui_text("replay", "Start Replay"), command=self.toggle_replay, style="Toolbar.TButton")
        self.replay_button.grid(row=0, column=0, sticky="ew", padx=6, pady=8)
        ttk.Button(controls, text=ui_text("clip", "Save Clip"), command=self.save_clip, style="Toolbar.TButton").grid(row=0, column=1, sticky="ew", padx=6, pady=8)
        self.recording_button = ttk.Button(controls, text=ui_text("record", "Start Recording"), command=self.toggle_recording, style="Toolbar.TButton")
        self.recording_button.grid(row=0, column=2, sticky="ew", padx=6, pady=8)
        ttk.Button(controls, text=ui_text("stop", "Stop All"), command=self.stop_all, style="Toolbar.TButton").grid(row=0, column=3, sticky="ew", padx=6, pady=8)
        ttk.Button(controls, text=ui_text("settings", "Save Settings"), command=self.save_settings, style="Toolbar.TButton").grid(row=0, column=4, sticky="ew", padx=6, pady=8)
        ttk.Button(controls, text=ui_text("tray", "Hide to Tray"), command=self.hide_window, style="Toolbar.TButton").grid(row=0, column=5, sticky="ew", padx=6, pady=8)

        library = ttk.Frame(controls)
        library.grid(row=1, column=0, columnspan=6, sticky="ew", padx=6, pady=(0, 8))
        for col in range(5):
            library.columnconfigure(col, weight=1)
        ttk.Button(library, text=ui_text("folder", "Open Clips Folder"), command=self.open_output).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(library, text=ui_text("play", "Open Last Clip"), command=self.open_last_clip).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(library, text=ui_text("gallery", "Show Last Clip"), command=self.show_last_clip).grid(row=0, column=2, sticky="ew", padx=6)
        ttk.Button(library, text=ui_text("clean", "Clean Storage"), command=self.clean_storage_now).grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Button(library, text=ui_text("download", "Check Updates"), command=self.check_for_updates).grid(row=0, column=4, sticky="ew", padx=(6, 0))
        ttk.Button(library, text="Check Setup", command=self.run_health_check).grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 6), pady=(6, 0))
        ttk.Button(library, text="Export Debug Report", command=self.export_debug_report).grid(row=1, column=2, columnspan=2, sticky="ew", padx=6, pady=(6, 0))

        settings = ttk.Frame(root)
        settings.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 8))
        settings.columnconfigure(0, weight=1, uniform="settings")
        settings.columnconfigure(1, weight=1, uniform="settings")

        left = ttk.Frame(settings)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)
        right = ttk.Frame(settings)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.columnconfigure(0, weight=1)

        source = ttk.LabelFrame(left, text=ui_text("source", "Capture Source"))
        source.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        source.columnconfigure(1, weight=1)
        ttk.Radiobutton(source, text=ui_text("monitor", "All screens"), variable=self.vars["capture_mode"], value="desktop_all").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Radiobutton(source, text=ui_text("monitor", "One monitor"), variable=self.vars["capture_mode"], value="monitor").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.monitor_combo = ttk.Combobox(source, state="readonly")
        self.monitor_combo.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        self.monitor_combo.bind("<<ComboboxSelected>>", self.on_monitor_selected)
        ttk.Radiobutton(source, text=ui_text("window", "Window/Game title"), variable=self.vars["capture_mode"], value="window").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.window_combo = ttk.Combobox(source, textvariable=self.vars["window_title"])
        self.window_combo.grid(row=2, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(source, text=ui_text("replay", "Refresh Windows"), command=self.refresh_windows).grid(row=2, column=2, padx=8, pady=4)
        ttk.Label(source, text=ui_text("backend", "Backend")).grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(source, state="readonly", textvariable=self.vars["capture_backend"], values=["auto", "ddagrab", "gdigrab", "obs"], width=14).grid(row=3, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(source, text="Minecraft OBS mode").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(
            source,
            state="readonly",
            textvariable=self.vars["obs_minecraft_capture_mode"],
            values=["specific_game", "display", "any_fullscreen"],
            width=16,
        ).grid(row=4, column=1, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(source, text="Capture desktop overlays (WGC)", variable=self.vars["capture_desktop_overlays"]).grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=4)

        video = ttk.LabelFrame(left, text=ui_text("video", "Video"))
        video.grid(row=1, column=0, sticky="ew")
        for col in range(4):
            video.columnconfigure(col, weight=1 if col in (1, 3) else 0)
        ttk.Label(video, text=ui_text("video", "FPS")).grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(video, from_=15, to=240, increment=15, textvariable=self.vars["framerate"], width=8).grid(row=0, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("clip", "Clip seconds")).grid(row=0, column=2, sticky="w", padx=8, pady=4)
        ttk.Spinbox(video, from_=10, to=600, increment=10, textvariable=self.vars["clip_seconds"], width=8).grid(row=0, column=3, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("replay", "Segment seconds")).grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(video, from_=2, to=15, increment=1, textvariable=self.vars["segment_seconds"], width=8).grid(row=1, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("ffmpeg", "Encoder")).grid(row=1, column=2, sticky="w", padx=8, pady=4)
        ttk.Combobox(video, state="readonly", textvariable=self.vars["video_encoder"], values=VIDEO_ENCODER_VALUES, width=14).grid(row=1, column=3, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("quality", "Quality")).grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(video, from_=15, to=35, increment=1, textvariable=self.vars["quality"], width=8).grid(row=2, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("container", "Container")).grid(row=2, column=2, sticky="w", padx=8, pady=4)
        ttk.Combobox(video, state="readonly", textvariable=self.vars["container"], values=["mkv", "mp4"], width=8).grid(row=2, column=3, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(video, text="Auto bitrate", variable=self.vars["auto_video_bitrate"], command=lambda: self.sync_auto_video_bitrate(force=True)).grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("quality", "Preset")).grid(row=3, column=2, sticky="w", padx=8, pady=4)
        self.auto_bitrate_preset_combo = ttk.Combobox(video, state="readonly", textvariable=self.vars["auto_bitrate_preset"], values=AUTO_BITRATE_PRESETS, width=10)
        self.auto_bitrate_preset_combo.grid(row=3, column=3, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("quality", "Bitrate mode")).grid(row=4, column=0, sticky="w", padx=8, pady=4)
        self.bitrate_mode_combo = ttk.Combobox(video, state="readonly", textvariable=self.vars["bitrate_mode"], values=["quality", "target"], width=10)
        self.bitrate_mode_combo.grid(row=4, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("video", "Target Mbps")).grid(row=4, column=2, sticky="w", padx=8, pady=4)
        self.video_bitrate_spin = ttk.Spinbox(video, from_=1, to=300, increment=1, textvariable=self.vars["video_bitrate_mbps"], width=8)
        self.video_bitrate_spin.grid(row=4, column=3, sticky="w", padx=8, pady=4)
        ttk.Label(video, text=ui_text("video", "Max Mbps")).grid(row=5, column=2, sticky="w", padx=8, pady=4)
        self.max_bitrate_spin = ttk.Spinbox(video, from_=1, to=500, increment=1, textvariable=self.vars["max_bitrate_mbps"], width=8)
        self.max_bitrate_spin.grid(row=5, column=3, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(video, text="Auto OBS replay RAM", variable=self.vars["obs_replay_ram_auto"], command=lambda: self.sync_auto_obs_replay_buffer(force=True)).grid(row=6, column=0, sticky="w", padx=8, pady=4)
        self.obs_replay_buffer_spin = ttk.Spinbox(video, from_=64, to=2048, increment=64, textvariable=self.vars["obs_replay_buffer_mb"], width=8)
        self.obs_replay_buffer_spin.grid(row=6, column=1, sticky="w", padx=8, pady=4)

        audio = ttk.LabelFrame(right, text=ui_text("audio", "Audio"))
        audio.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        audio.columnconfigure(1, weight=1)
        ttk.Checkbutton(audio, text=ui_text("mic", "Mic"), variable=self.vars["mic_enabled"]).grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.mic_combo = ttk.Combobox(audio, textvariable=self.vars["mic_device"])
        self.mic_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(audio, text=ui_text("replay", "Scan Audio"), command=self.scan_audio).grid(row=0, column=2, sticky="e", padx=8, pady=4)
        ttk.Checkbutton(audio, text=ui_text("desktop", "Desktop audio"), variable=self.vars["desktop_audio_enabled"]).grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.desktop_audio_combo = ttk.Combobox(audio, textvariable=self.vars["desktop_audio_device"])
        self.desktop_audio_combo.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Combobox(audio, state="readonly", textvariable=self.vars["desktop_audio_backend"], values=["wasapi", "dshow"], width=8).grid(row=1, column=2, sticky="e", padx=8, pady=4)
        ttk.Label(audio, text=ui_text("clip", "Clip audio offset ms")).grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(audio, from_=-20000, to=20000, increment=50, textvariable=self.vars["audio_offset_ms"], width=8).grid(row=2, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(audio, text=ui_text("record", "Recording audio offset ms")).grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(audio, from_=-20000, to=20000, increment=50, textvariable=self.vars["recording_audio_offset_ms"], width=8).grid(row=3, column=1, sticky="w", padx=8, pady=4)

        hud = ttk.LabelFrame(right, text=ui_text("settings", "HUD and Feedback"))
        hud.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for col in range(4):
            hud.columnconfigure(col, weight=1 if col in (1, 3) else 0)
        ttk.Checkbutton(hud, text=ui_text("record", "Capture status icons"), variable=self.vars["recording_indicator_enabled"]).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(hud, text=ui_text("audio", "Event sounds"), variable=self.vars["event_sounds_enabled"]).grid(row=0, column=2, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(hud, text=ui_text("clip", "Close HUD after clip"), variable=self.vars["hide_overlay_after_clip"]).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(hud, text=ui_text("settings", "Fullscreen-safe HUD"), variable=self.vars["fullscreen_safe_hud"]).grid(row=1, column=2, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Label(hud, text=ui_text("audio", "Toast ms")).grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(hud, from_=500, to=10000, increment=250, textvariable=self.vars["toast_duration_ms"], width=8).grid(row=2, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(hud, text=ui_text("gallery", "Gallery clips")).grid(row=2, column=2, sticky="w", padx=8, pady=4)
        ttk.Spinbox(hud, from_=3, to=50, increment=1, textvariable=self.vars["gallery_limit"], width=8).grid(row=2, column=3, sticky="w", padx=8, pady=4)
        ttk.Label(hud, text=ui_text("tray", "Toast position")).grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(hud, state="readonly", textvariable=self.vars["toast_position"], values=["top_right", "bottom_right", "top_left", "bottom_left"], width=14).grid(row=3, column=1, sticky="w", padx=8, pady=4)

        storage = ttk.LabelFrame(right, text=ui_text("storage", "Storage and Startup"))
        storage.grid(row=2, column=0, sticky="ew")
        storage.columnconfigure(1, weight=1)
        ttk.Label(storage, text=ui_text("folder", "Output")).grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(storage, textvariable=self.vars["output_dir"]).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(storage, text=ui_text("browse", "Browse"), command=self.browse_output).grid(row=0, column=2, sticky="e", padx=8, pady=4)
        ttk.Label(storage, text=ui_text("ffmpeg", "FFmpeg")).grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(storage, textvariable=self.vars["ffmpeg_path"]).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(storage, text=ui_text("browse", "Browse"), command=self.browse_ffmpeg).grid(row=1, column=2, sticky="e", padx=8, pady=4)
        ttk.Label(storage, text="OBS").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(storage, textvariable=self.vars["obs_path"]).grid(row=2, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(storage, text=ui_text("browse", "Browse"), command=self.browse_obs).grid(row=2, column=2, sticky="e", padx=8, pady=4)
        ttk.Checkbutton(storage, text=ui_text("gallery", "Organize by game/app"), variable=self.vars["organize_clips_by_game"]).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Label(storage, text=ui_text("storage", "Max storage GB")).grid(row=3, column=2, sticky="w", padx=8, pady=4)
        ttk.Spinbox(storage, from_=0, to=5000, increment=5, textvariable=self.vars["max_storage_gb"], width=8).grid(row=4, column=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Checkbutton(storage, text=ui_text("replay", "Reset replay window after clip"), variable=self.vars["reset_replay_after_clip"]).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(storage, text=ui_text("startup", "Start with Windows"), variable=self.vars["start_with_windows"]).grid(row=5, column=0, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(storage, text=ui_text("replay", "Start replay on launch"), variable=self.vars["auto_start_replay"]).grid(row=5, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(storage, text=ui_text("download", "Check updates on launch"), variable=self.vars["check_updates_on_start"]).grid(row=6, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(storage, text="Use per-game profiles", variable=self.vars["use_game_profiles"]).grid(row=7, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Button(storage, text="Save Game Profile", command=self.save_game_profile_for_current_game).grid(row=8, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 6))
        ttk.Button(storage, text="Delete Profile", command=self.delete_game_profile_for_current_game).grid(row=8, column=2, sticky="ew", padx=8, pady=(2, 6))

        log_frame = ttk.LabelFrame(root, text=ui_text("hotkey", "Log"))
        log_frame.grid(row=4, column=0, sticky="nsew", padx=14, pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=9, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)
        self.refresh_status_panel()

    def configure_dark_theme(self):
        self.ui_colors = {
            "bg": "#0b1017",
            "bg_soft": "#0f141c",
            "sidebar": "#0d1118",
            "panel": "#171d26",
            "panel_2": "#202733",
            "panel_3": "#242c38",
            "panel_hover": "#293241",
            "border": "#303846",
            "border_soft": "#232a35",
            "text": "#f4f7fb",
            "muted": "#a5afbf",
            "muted_dark": "#748092",
            "accent": "#80d51a",
            "accent_hover": "#91ea20",
            "accent_dark": "#172a0c",
            "danger": "#d85d5d",
        }
        colors = self.ui_colors
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Segoe UI", 9))
        style.configure("TFrame", background=colors["bg"])
        style.configure("Card.TFrame", background=colors["panel"])
        style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
        style.configure("Card.TLabel", background=colors["panel"], foreground=colors["text"])
        style.configure("Muted.TLabel", background=colors["bg"], foreground=colors["muted"])
        style.configure("Muted.Card.TLabel", background=colors["panel"], foreground=colors["muted"])
        style.configure("Title.TLabel", background=colors["bg"], foreground=colors["text"], font=("Segoe UI", 18, "bold"))
        style.configure("Status.TLabel", background=colors["panel"], foreground=colors["text"], padding=(10, 6), anchor="center")
        style.configure("Toolbar.TButton", padding=(10, 7), font=("Segoe UI", 9))
        style.configure("TButton", background=colors["panel_2"], foreground=colors["text"], borderwidth=0, focusthickness=0)
        style.map(
            "TButton",
            background=[("active", colors["panel_hover"]), ("pressed", colors["accent_dark"])],
            foreground=[("disabled", colors["muted"]), ("active", colors["text"])],
        )
        style.configure("Accent.TButton", background=colors["accent"], foreground="#081008", borderwidth=0, focusthickness=0, padding=(12, 8))
        style.map("Accent.TButton", background=[("active", colors["accent_hover"]), ("pressed", colors["accent_dark"])])
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=colors["panel_3"],
            background=colors["accent"],
            darkcolor=colors["accent"],
            lightcolor=colors["accent"],
            bordercolor=colors["border"],
        )
        style.configure("Card.TCheckbutton", background=colors["panel"], foreground=colors["text"], focuscolor=colors["panel"])
        style.map(
            "Card.TCheckbutton",
            background=[("active", colors["panel"])],
            foreground=[("disabled", colors["muted"]), ("active", colors["text"])],
        )
        style.configure("Card.TRadiobutton", background=colors["panel"], foreground=colors["text"], focuscolor=colors["panel"])
        style.map(
            "Card.TRadiobutton",
            background=[("active", colors["panel"])],
            foreground=[("disabled", colors["muted"]), ("active", colors["text"])],
        )
        for widget_style in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(
                widget_style,
                fieldbackground="#eef2f7",
                background=colors["panel_2"],
                foreground="#111827",
                bordercolor=colors["border"],
                lightcolor=colors["border"],
                darkcolor=colors["border"],
                arrowcolor=colors["text"],
            )
        style.configure(
            "Gallery.TCombobox",
            fieldbackground=colors["panel_2"],
            background=colors["panel_2"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            lightcolor=colors["border"],
            darkcolor=colors["border"],
            arrowcolor=colors["text"],
            padding=(8, 6),
        )
        style.map(
            "Gallery.TCombobox",
            fieldbackground=[("readonly", colors["panel_2"])],
            foreground=[("readonly", colors["text"])],
            selectbackground=[("readonly", colors["panel_2"])],
            selectforeground=[("readonly", colors["text"])],
        )
        for modern_style in ("Modern.TEntry", "Modern.TCombobox", "Modern.TSpinbox"):
            style.configure(
                modern_style,
                fieldbackground=colors["panel_2"],
                background=colors["panel_2"],
                foreground=colors["text"],
                bordercolor=colors["border"],
                lightcolor=colors["border"],
                darkcolor=colors["border"],
                arrowcolor=colors["text"],
                insertcolor=colors["text"],
                padding=(9, 7),
            )
            style.map(
                modern_style,
                fieldbackground=[("readonly", colors["panel_2"]), ("disabled", colors["panel_3"])],
                foreground=[("readonly", colors["text"]), ("disabled", colors["muted_dark"])],
                selectbackground=[("readonly", colors["panel_2"])],
                selectforeground=[("readonly", colors["text"])],
            )
        style.configure("Modern.TCheckbutton", background=colors["panel"], foreground=colors["text"], focuscolor=colors["panel"], font=("Segoe UI", 10, "bold"), padding=(0, 2))
        style.map("Modern.TCheckbutton", background=[("active", colors["panel"])], foreground=[("disabled", colors["muted_dark"]), ("active", colors["text"])])
        style.configure("Modern.TRadiobutton", background=colors["panel"], foreground=colors["text"], focuscolor=colors["panel"], font=("Segoe UI", 10, "bold"), padding=(0, 2))
        style.map("Modern.TRadiobutton", background=[("active", colors["panel"])], foreground=[("disabled", colors["muted_dark"]), ("active", colors["text"])])

    def apply_dark_titlebar(self):
        if os.name != "nt":
            return
        try:
            self.root.update_idletasks()
            user32 = ctypes.windll.user32
            dwmapi = ctypes.windll.dwmapi
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id()
            enabled = ctypes.c_int(1)
            for attribute in (20, 19):
                try:
                    dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled))
                except Exception:
                    pass
            caption_color = ctypes.c_int(0x17100B)
            text_color = ctypes.c_int(0xFBF7F4)
            for attribute, value in ((35, caption_color), (36, text_color)):
                try:
                    dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
                except Exception:
                    pass
        except Exception:
            pass

    def create_card(self, parent, bg=None):
        colors = self.ui_colors
        frame = tk.Frame(
            parent,
            bg=bg or colors["panel"],
            highlightbackground=colors["border"],
            highlightcolor=colors["border"],
            highlightthickness=1,
            bd=0,
        )
        return frame

    def create_section(self, parent, title, subtitle=""):
        colors = self.ui_colors
        card = self.create_card(parent)
        header = tk.Frame(card, bg=colors["panel"])
        header.pack(fill="x", padx=18, pady=(15, 8))
        tk.Label(header, text=title, bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(header, text=subtitle, bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(3, 0))
        body = tk.Frame(card, bg=colors["panel"])
        body.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        return card, body

    def build_settings_page_header(self, parent, title, subtitle, save=True):
        colors = self.ui_colors
        header = tk.Frame(parent, bg=colors["bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 22))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text=title, bg=colors["bg"], fg=colors["text"], font=("Segoe UI", 20, "bold"), anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(header, text=subtitle, bg=colors["bg"], fg=colors["muted"], font=("Segoe UI", 11), anchor="w").grid(row=1, column=0, sticky="ew", pady=(2, 0))
        if save:
            state = tk.Label(header, text="All changes saved", bg=colors["bg"], fg=colors["muted"], font=("Segoe UI", 9), anchor="e")
            state.grid(row=0, column=1, sticky="e", padx=(16, 12))
            button = self.small_action_button(header, "Save changes", self.save_settings, accent=True, icon_key="check")
            button.grid(row=0, column=2, rowspan=2, sticky="e")
            self.settings_state_labels.append(state)
            self.settings_save_buttons.append(button)
        return header

    def create_settings_panel(self, parent, title, subtitle="", icon_key="settings"):
        colors = self.ui_colors
        panel = self.dashboard_panel(parent)
        panel.columnconfigure(0, weight=1)
        header = tk.Frame(panel, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(17, 12))
        header.columnconfigure(1, weight=1)
        icon = self.create_icon_canvas(header, icon_key, size=24, fg=colors["accent"], bg=colors["panel"])
        icon.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 10))
        tk.Label(header, text=title, bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 12, "bold"), anchor="w").grid(row=0, column=1, sticky="ew")
        if subtitle:
            tk.Label(header, text=subtitle, bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9), anchor="w", justify="left", wraplength=520).grid(row=1, column=1, sticky="ew", pady=(3, 0))
        body = tk.Frame(panel, bg=colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        panel.rowconfigure(1, weight=1)
        return panel, body

    def create_scrollable_settings_content(self, parent, row=1):
        colors = self.ui_colors
        host = tk.Frame(parent, bg=colors["bg"])
        host.grid(row=row, column=0, sticky="nsew")
        host.columnconfigure(0, weight=1)
        host.rowconfigure(0, weight=1)
        canvas = tk.Canvas(host, bg=colors["bg"], highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas, bg=colors["bg"])
        window = canvas.create_window((0, 0), window=content, anchor="nw")
        scroll_state = {"visible": False}

        def update_scrollbar():
            if not canvas.winfo_exists() or not content.winfo_exists():
                return
            canvas.configure(scrollregion=canvas.bbox("all"))
            overflowing = content.winfo_reqheight() > canvas.winfo_height() + 2
            if overflowing and not scroll_state["visible"]:
                scrollbar.grid(row=0, column=1, sticky="ns", padx=(10, 0))
                scroll_state["visible"] = True
            elif not overflowing and scroll_state["visible"]:
                canvas.yview_moveto(0)
                scrollbar.grid_remove()
                scroll_state["visible"] = False

        def content_configured(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.after_idle(update_scrollbar)

        def canvas_configured(event):
            canvas.itemconfigure(window, width=max(1, event.width))
            canvas.after_idle(update_scrollbar)

        content.bind("<Configure>", content_configured, add="+")
        canvas.bind("<Configure>", canvas_configured, add="+")
        canvas.configure(yscrollcommand=scrollbar.set)

        def scroll(event):
            if not scroll_state["visible"]:
                return None
            delta = int(getattr(event, "delta", 0) or 0)
            steps = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            canvas.yview_scroll(steps * 3, "units")
            return "break"

        def bind_tree():
            if not content.winfo_exists():
                return
            stack = [canvas, content]
            while stack:
                widget = stack.pop()
                widget.bind("<MouseWheel>", scroll, add="+")
                stack.extend(widget.winfo_children())

        self.root.after_idle(bind_tree)
        content._shadowclip_scroll_host = host
        content._shadowclip_scroll_canvas = canvas
        content._shadowclip_scrollbar = scrollbar
        content._shadowclip_scroll_state = scroll_state
        content._shadowclip_update_scrollbar = update_scrollbar
        return content

    def settings_field_label(self, parent, title, detail, row, column=0, columnspan=1):
        colors = self.ui_colors
        block = tk.Frame(parent, bg=colors["panel"])
        block.grid(row=row, column=column, columnspan=columnspan, sticky="ew", pady=(5, 4))
        tk.Label(block, text=title, bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
        if detail:
            tk.Label(block, text=detail, bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=360).pack(fill="x", pady=(2, 0))
        return block

    def settings_toggle(self, parent, title, detail, variable, row, column=0, columnspan=1, command=None):
        colors = self.ui_colors
        block = tk.Frame(parent, bg=colors["panel"])
        block.grid(row=row, column=column, columnspan=columnspan, sticky="ew", pady=6)
        check = ttk.Checkbutton(block, text=title, variable=variable, command=command, style="Modern.TCheckbutton")
        check.pack(fill="x", anchor="w")
        if detail:
            tk.Label(block, text=detail, bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=420).pack(fill="x", padx=(23, 0), pady=(2, 0))
        return check

    def mark_settings_dirty(self, *_args):
        if not self.settings_dirty_tracking:
            return
        self.settings_dirty = True
        self.update_settings_dirty_ui()

    def clear_settings_dirty(self):
        self.settings_dirty = False
        self.update_settings_dirty_ui()

    def enable_settings_dirty_tracking(self):
        self.settings_dirty_tracking = True
        self.clear_settings_dirty()

    def update_settings_dirty_ui(self):
        text = "Unsaved changes" if self.settings_dirty else "All changes saved"
        color = self.ui_colors["accent"] if self.settings_dirty else self.ui_colors["muted"]
        for label in self.settings_state_labels:
            try:
                label.configure(text=text, fg=color)
            except tk.TclError:
                pass

    def add_button_hover(self, button, normal=None, hover=None):
        colors = self.ui_colors
        normal = normal or button.cget("background")
        hover = hover or colors["panel_hover"]
        button.configure(activebackground=hover, activeforeground=button.cget("foreground"), relief="flat", bd=0)
        button.bind("<Enter>", lambda _event: button.configure(bg=hover))
        button.bind("<Leave>", lambda _event: button.configure(bg=normal))

    def action_button(self, parent, title, detail, command, accent=False):
        colors = self.ui_colors
        normal = colors["accent"] if accent else colors["panel_2"]
        hover = colors["accent_hover"] if accent else colors["panel_hover"]
        fg = "#071007" if accent else colors["text"]
        text = title if not detail else f"{title}\n{detail}"
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=normal,
            fg=fg,
            activeforeground=fg,
            font=("Segoe UI", 10, "bold"),
            justify="center",
            cursor="hand2",
            padx=16,
            pady=18,
        )
        self.add_button_hover(button, normal, hover)
        return button

    def small_action_button(self, parent, title, command, accent=False, icon_key=None):
        colors = self.ui_colors
        normal = colors["accent"] if accent else colors["panel_2"]
        hover = colors["accent_hover"] if accent else colors["panel_hover"]
        fg = "#071007" if accent else colors["text"]
        icon = self.icon_image(icon_key, 18, fg) if icon_key else None
        button = tk.Button(
            parent,
            text=title,
            command=command,
            bg=normal,
            fg=fg,
            activeforeground=fg,
            image=icon,
            compound="left",
            font=("Segoe UI", 9, "bold" if accent else "normal"),
            cursor="hand2",
            padx=12,
            pady=8,
        )
        if icon:
            button._shadowclip_icon_ref = icon
        self.add_button_hover(button, normal, hover)
        return button

    def dashboard_icon(self, key):
        icons = {
            "home": "\u2302",
            "clips": "\u25b7",
            "capture": "\u2723",
            "video": "\u25a6",
            "audio": "\u266a",
            "hud": "\u25a7",
            "storage": "\u25ce",
            "updates": "\u21e7",
            "logs": "\u2630",
            "settings": "\u2699",
            "replay": "\u27f3",
            "record": "\u25cf",
            "encoder": "\u2699",
            "timer": "\u23f1",
            "wave": "\u266b",
            "folder": "\u25a3",
            "trash": "\u232b",
            "open": "\u25f1",
            "more": "\u2026",
            "check": "\u2713",
        }
        return icons.get(key, "")

    def canonical_icon_key(self, key):
        return {
            "gallery": "image",
            "clip_save": "clapper",
            "wave": "audio_bars",
            "hotkeys": "settings",
        }.get(str(key or ""), str(key or ""))

    def icon_variant_for_color(self, fg):
        accent = self.ui_colors.get("accent", "#80d51a").lower()
        color = str(fg or "").lower()
        if color == accent:
            return "accent"
        if color in ("#071007", "#0b1017", "#10151d"):
            return "dark"
        return "light"

    def icon_image(self, key, size=32, fg=None):
        key = self.canonical_icon_key(key)
        if not key:
            return None
        variant = self.icon_variant_for_color(fg or self.ui_colors.get("accent", "#80d51a"))
        cache_key = (key, int(size), variant)
        cached = getattr(self, "icon_images", {}).get(cache_key)
        if cached is not None:
            return cached
        icon_path = resource_path(f"assets/icons/{key}_{int(size)}_{variant}.png")
        if not icon_path.exists():
            return None
        try:
            image = tk.PhotoImage(file=str(icon_path))
        except tk.TclError:
            return None
        self.icon_images[cache_key] = image
        return image

    def create_icon_canvas(self, parent, key, size=32, fg=None, bg=None):
        colors = self.ui_colors
        image = self.icon_image(key, size, fg or colors["accent"])
        if image is not None:
            label = tk.Label(parent, image=image, bg=bg or colors["panel"], bd=0, highlightthickness=0)
            label._shadowclip_icon_key = self.canonical_icon_key(key)
            label._shadowclip_icon_size = int(size)
            label._shadowclip_icon_ref = image
            return label
        canvas = tk.Canvas(
            parent,
            width=size,
            height=size,
            bg=bg or colors["panel"],
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.draw_dashboard_icon(canvas, key, size, fg or colors["accent"])
        return canvas

    def set_icon_colors(self, canvas, fg=None, bg=None):
        if hasattr(canvas, "_shadowclip_icon_key"):
            if bg is not None:
                try:
                    canvas.configure(bg=bg)
                except tk.TclError:
                    pass
            image = self.icon_image(canvas._shadowclip_icon_key, getattr(canvas, "_shadowclip_icon_size", 32), fg)
            if image is not None:
                try:
                    canvas.configure(image=image)
                    canvas._shadowclip_icon_ref = image
                except tk.TclError:
                    pass
            return
        try:
            if bg is not None:
                canvas.configure(bg=bg)
            if fg is not None:
                canvas.itemconfigure("icon_line", fill=fg)
                canvas.itemconfigure("icon_outline", outline=fg)
                canvas.itemconfigure("icon_fill", fill=fg)
                canvas.itemconfigure("icon_text", fill=fg)
        except tk.TclError:
            pass

    def draw_dashboard_icon(self, canvas, key, size, color):
        scale = size / 48.0
        width = max(2, int(round(size / 17)))

        def xy(*values):
            return [round(value * scale, 2) for value in values]

        def line(*values, w=None):
            canvas.create_line(
                *xy(*values),
                fill=color,
                width=w or width,
                capstyle="round",
                joinstyle="round",
                tags=("icon_line",),
            )

        def rect(x1, y1, x2, y2, w=None):
            canvas.create_rectangle(
                *xy(x1, y1, x2, y2),
                outline=color,
                width=w or width,
                tags=("icon_outline",),
            )

        def oval(x1, y1, x2, y2, w=None, fill=""):
            tags = ("icon_fill",) if fill else ("icon_outline",)
            canvas.create_oval(
                *xy(x1, y1, x2, y2),
                outline=color if not fill else "",
                fill=color if fill else "",
                width=w or width,
                tags=tags,
            )

        def arc(x1, y1, x2, y2, start, extent, w=None):
            canvas.create_arc(
                *xy(x1, y1, x2, y2),
                start=start,
                extent=extent,
                style="arc",
                outline=color,
                width=w or width,
                tags=("icon_outline",),
            )

        def poly(*values, fill=False):
            canvas.create_polygon(
                *xy(*values),
                outline=color,
                fill=color if fill else "",
                width=width,
                tags=("icon_fill",) if fill else ("icon_outline",),
            )

        key = {
            "gallery": "image",
            "clip_save": "clapper",
            "wave": "audio_bars",
        }.get(key, key)

        if key == "home":
            line(10, 23, 24, 12, 38, 23)
            line(15, 22, 15, 37, 33, 37, 33, 22)
            line(21, 37, 21, 29, 27, 29, 27, 37)
        elif key == "clips":
            rect(11, 13, 37, 35)
            poly(21, 19, 21, 29, 30, 24, fill=True)
        elif key == "capture":
            oval(22, 22, 26, 26, fill=True)
            line(24, 8, 24, 17)
            line(24, 31, 24, 40)
            line(8, 24, 17, 24)
            line(31, 24, 40, 24)
            line(20, 12, 24, 8, 28, 12)
            line(20, 36, 24, 40, 28, 36)
            line(12, 20, 8, 24, 12, 28)
            line(36, 20, 40, 24, 36, 28)
        elif key == "video":
            rect(12, 10, 36, 38)
            line(18, 10, 18, 38)
            line(30, 10, 30, 38)
            for y in (15, 24, 33):
                line(13, y, 16, y, w=max(2, width - 1))
                line(32, y, 35, y, w=max(2, width - 1))
        elif key == "audio":
            line(10, 20, 16, 20, 25, 13, 25, 35, 16, 28, 10, 28, 10, 20)
            arc(25, 18, 36, 30, -45, 90)
            arc(26, 12, 43, 36, -45, 90)
        elif key == "hud":
            line(11, 18, 11, 11, 18, 11)
            line(30, 11, 37, 11, 37, 18)
            line(37, 30, 37, 37, 30, 37)
            line(18, 37, 11, 37, 11, 30)
            rect(18, 18, 30, 30, w=max(1, width - 1))
        elif key == "storage":
            arc(12, 9, 36, 21, 0, 360)
            line(12, 15, 12, 34)
            line(36, 15, 36, 34)
            arc(12, 28, 36, 40, 180, 180)
            arc(12, 18, 36, 30, 180, 180, w=max(1, width - 1))
        elif key == "updates":
            line(15, 33, 33, 33)
            arc(10, 18, 25, 34, 95, 175)
            arc(19, 12, 34, 28, 30, 220)
            arc(28, 18, 41, 34, -20, 135)
            line(24, 34, 24, 18)
            line(18, 24, 24, 18, 30, 24)
        elif key == "logs":
            rect(12, 10, 36, 38)
            for y in (17, 24, 31):
                line(18, y, 32, y)
                oval(14, y - 1.5, 16, y + 1.5, fill=True)
        elif key == "settings":
            oval(18, 18, 30, 30)
            for x1, y1, x2, y2 in (
                (24, 8, 24, 14),
                (24, 34, 24, 40),
                (8, 24, 14, 24),
                (34, 24, 40, 24),
                (13, 13, 17, 17),
                (31, 31, 35, 35),
                (35, 13, 31, 17),
                (17, 31, 13, 35),
            ):
                line(x1, y1, x2, y2)
        elif key == "replay":
            arc(10, 10, 38, 38, 35, 285)
            line(37, 17, 37, 28, 27, 27)
        elif key == "record":
            oval(13, 13, 35, 35)
            oval(20, 20, 28, 28, fill=True)
        elif key == "encoder":
            rect(15, 15, 33, 33)
            oval(21, 21, 27, 27, fill=True)
            for v in (18, 24, 30):
                line(v, 10, v, 15)
                line(v, 33, v, 38)
                line(10, v, 15, v)
                line(33, v, 38, v)
        elif key == "timer":
            oval(12, 14, 36, 38)
            line(20, 9, 28, 9)
            line(24, 9, 24, 14)
            line(24, 24, 24, 17)
            line(24, 24, 30, 28)
            line(34, 13, 38, 17)
        elif key == "audio_bars":
            for x, y1, y2 in ((12, 22, 28), (18, 16, 34), (24, 10, 40), (30, 16, 34), (36, 22, 28)):
                line(x, y1, x, y2, w=max(3, width + 1))
        elif key == "image":
            rect(11, 12, 37, 36)
            oval(28, 17, 32, 21, fill=True)
            line(15, 32, 22, 24, 28, 30, 32, 26, 37, 32)
        elif key == "folder":
            line(9, 17, 20, 17, 23, 21, 39, 21, 39, 36, 9, 36, 9, 17)
        elif key == "clapper":
            rect(13, 18, 35, 35)
            line(13, 18, 35, 18)
            line(17, 18, 22, 12)
            line(25, 18, 30, 12)
            line(13, 18, 17, 12, 35, 12)
        elif key == "trash":
            line(16, 17, 32, 17)
            line(20, 13, 28, 13)
            rect(18, 19, 30, 36)
            line(22, 23, 22, 32)
            line(26, 23, 26, 32)
        elif key == "open":
            rect(13, 17, 31, 35)
            line(25, 13, 35, 13, 35, 23)
            line(23, 25, 35, 13)
        elif key == "check":
            line(14, 25, 21, 32, 35, 16, w=max(3, width + 1))
        else:
            canvas.create_text(
                size / 2,
                size / 2,
                text=self.dashboard_icon(key),
                fill=color,
                font=("Segoe UI Symbol", max(12, int(size * 0.52)), "bold"),
                tags=("icon_text",),
            )

    def bind_click_tree(self, widget, command):
        def invoke(_event):
            command()
            return "break"

        stack = [widget]
        while stack:
            current = stack.pop()
            try:
                current.configure(cursor="hand2")
            except tk.TclError:
                pass
            current.bind("<Button-1>", invoke, add="+")
            stack.extend(current.winfo_children())

    def set_label_text(self, attr, text, fg=None):
        widget = getattr(self, attr, None)
        if widget is None:
            return
        try:
            if fg:
                widget.configure(text=text, fg=fg)
            else:
                widget.configure(text=text)
        except tk.TclError:
            pass

    def dashboard_panel(self, parent, bg=None):
        frame = self.create_card(parent, bg=bg or self.ui_colors["panel"])
        frame.configure(highlightbackground=self.ui_colors["border"], highlightthickness=1)
        return frame

    def make_metric_card(self, parent, icon_key, title, value_attr, detail_attr, active=False, command=None):
        colors = self.ui_colors
        normal = colors["panel"]
        hover = colors["panel_hover"]
        card = self.dashboard_panel(parent)
        card.columnconfigure(1, weight=1)
        icon_fg = colors["accent"] if active else "#dce3ee"
        icon = self.create_icon_canvas(card, icon_key, size=48, fg=icon_fg, bg=normal)
        icon.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(18, 12), pady=18)
        title_label = tk.Label(card, text=title, bg=normal, fg=colors["text"], font=("Segoe UI", 10), anchor="w")
        title_label.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=(18, 0))
        value = tk.Label(card, text="", bg=normal, fg=colors["accent"] if active else colors["text"], font=("Segoe UI", 15, "bold"), anchor="w")
        value.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(1, 0))
        detail = tk.Label(card, text="", bg=normal, fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        detail.grid(row=2, column=1, sticky="ew", padx=(0, 16), pady=(16, 18))
        setattr(self, value_attr, value)
        setattr(self, detail_attr, detail)
        if command:
            widgets = (card, icon, title_label, value, detail)

            def enter(_event):
                card.configure(bg=hover, highlightbackground=colors["accent"])
                for widget in (title_label, value, detail):
                    widget.configure(bg=hover)
                self.set_icon_colors(icon, icon_fg, hover)

            def leave(_event):
                card.configure(bg=normal, highlightbackground=colors["border"])
                for widget in (title_label, value, detail):
                    widget.configure(bg=normal)
                self.set_icon_colors(icon, icon_fg, normal)

            for widget in widgets:
                widget.bind("<Enter>", enter, add="+")
                widget.bind("<Leave>", leave, add="+")
            self.bind_click_tree(card, command)
            card.configure(takefocus=1)
            card.bind("<Return>", lambda _event: command(), add="+")
            card.bind("<space>", lambda _event: command(), add="+")
            card._shadowclip_command = command
            card._shadowclip_normal_bg = normal
            card._shadowclip_hover_bg = hover
        return card

    def make_action_card(self, parent, icon_key, title, detail, command):
        colors = self.ui_colors
        normal = colors["panel"]
        hover = colors["panel_hover"]
        card = self.dashboard_panel(parent)
        card.configure(bg=normal)
        card.columnconfigure(1, weight=1)
        icon_ring = tk.Frame(card, bg=normal, highlightbackground=colors["border"], highlightthickness=3, width=86, height=86)
        icon_ring.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(36, 24), pady=28)
        icon_ring.grid_propagate(False)
        icon = self.create_icon_canvas(icon_ring, icon_key, size=46, fg=colors["accent"], bg=normal)
        icon.place(relx=0.5, rely=0.5, anchor="center")
        title_label = tk.Label(card, text=title, bg=normal, fg=colors["text"], font=("Segoe UI", 15, "bold"), anchor="w")
        title_label.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=(38, 0))
        detail_label = tk.Label(card, text=detail, bg=normal, fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        detail_label.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=(4, 34))
        accent = tk.Frame(card, bg=colors["accent"], height=4)
        accent.grid(row=2, column=0, columnspan=2, sticky="ew")

        def enter(_event):
            for child in (card, icon_ring, title_label, detail_label):
                try:
                    child.configure(bg=hover)
                except tk.TclError:
                    pass
            self.set_icon_colors(icon, colors["accent"], hover)

        def leave(_event):
            for child in (card, icon_ring, title_label, detail_label):
                try:
                    child.configure(bg=normal)
                except tk.TclError:
                    pass
            self.set_icon_colors(icon, colors["accent"], normal)

        for widget in (card, icon_ring, icon, title_label, detail_label):
            widget.bind("<Enter>", enter, add="+")
            widget.bind("<Leave>", leave, add="+")
        self.bind_click_tree(card, command)
        return card

    def output_path_label(self):
        raw = self.vars["output_dir"].get() if "output_dir" in self.vars else DEFAULT_CONFIG["output_dir"]
        return str(raw or DEFAULT_CONFIG["output_dir"])

    def compact_path_label(self, path, max_chars=26):
        text = str(path or "")
        if len(text) <= max_chars:
            return text
        drive, tail = os.path.splitdrive(text)
        parts = Path(text).parts
        if drive and len(parts) >= 2:
            return f"{drive}\\...\\{parts[-1]}"
        return f"...{text[-max_chars + 3:]}"

    def latest_clip_dashboard_info(self):
        clip = self.manager.latest_clip_path()
        if not clip:
            return {
                "title": "No clip yet",
                "modified": "Save a replay first",
                "duration": f"{int(self.vars['clip_seconds'].get() or 0):d}s buffer",
                "resolution": "",
                "size": "",
            }
        try:
            stat = clip.stat()
            modified_dt = datetime.fromtimestamp(stat.st_mtime)
            today = datetime.now().date()
            modified = f"Today, {modified_dt:%H:%M}" if modified_dt.date() == today else modified_dt.strftime("%d.%m.%Y, %H:%M")
            size = format_file_size(stat.st_size)
        except OSError:
            modified = ""
            size = ""
        output_root = self.manager.output_dir()
        title = clip.parent.name if clip.parent != output_root else clip.stem
        width, height = self.video_dimensions_for_bitrate()
        return {
            "title": title[:32],
            "modified": modified,
            "duration": format_duration(int(self.vars["clip_seconds"].get() or 0)),
            "resolution": f"{width}x{height}",
            "size": size,
        }

    def folder_size_bytes(self, folder, max_files=5000):
        total = 0
        count = 0
        try:
            for path in Path(folder).rglob("*"):
                if not path.is_file():
                    continue
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
                count += 1
                if count >= max_files:
                    break
        except OSError:
            return 0
        return total

    def storage_dashboard_info(self):
        output_dir = expand_path(self.output_path_label())
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            usage = shutil.disk_usage(str(output_dir))
            free_text = f"{format_file_size(usage.free)} free"
        except OSError:
            usage = None
            free_text = ""
        try:
            max_storage_gb = float(self.vars["max_storage_gb"].get() or 0)
        except (TypeError, ValueError, tk.TclError):
            max_storage_gb = 0
        if max_storage_gb > 0:
            used_bytes = self.folder_size_bytes(output_dir)
            limit_bytes = max_storage_gb * 1024 ** 3
            percent = 0 if limit_bytes <= 0 else max(0, min(1, used_bytes / limit_bytes))
            caption = f"{format_file_size(used_bytes)} / {max_storage_gb:g} GB ({int(percent * 100)}%)"
        elif usage:
            used_bytes = usage.total - usage.free
            percent = 0 if usage.total <= 0 else max(0, min(1, used_bytes / usage.total))
            caption = f"{format_file_size(used_bytes)} / {format_file_size(usage.total)} ({int(percent * 100)}%)"
        else:
            percent = 0
            caption = "Storage unavailable"
        return str(output_dir), free_text, caption, percent

    def form_label(self, parent, text, row, column=0):
        label = ttk.Label(parent, text=text, style="Card.TLabel")
        label.grid(row=row, column=column, sticky="w", padx=(0, 10), pady=7)
        return label

    def show_main_page(self, page_key):
        page = getattr(self, "pages", {}).get(page_key)
        if not page:
            return
        page.tkraise()
        self.active_page = page_key
        colors = self.ui_colors
        for key, parts in getattr(self, "nav_buttons", {}).items():
            active = key == page_key
            row = parts["row"]
            strip = parts["strip"]
            icon = parts["icon"]
            label = parts["label"]
            inactive_bg = colors["panel"] if key == "hotkeys" else colors["sidebar"]
            bg = colors["panel_2"] if active else inactive_bg
            icon_fg = colors["accent"] if active else "#d7dee9"
            label_fg = colors["text"] if active else "#d7dee9"
            row.configure(bg=bg, highlightbackground=colors["border"] if (active or key == "hotkeys") else colors["sidebar"])
            strip.configure(bg=colors["accent"] if active else bg)
            self.set_icon_colors(icon, icon_fg, bg)
            label.configure(bg=bg, fg=label_fg)
        self.update_status_bar()
        if page_key == "clips":
            self.root.after(0, lambda: self.refresh_clip_library(force=False))

    def create_nav_button(self, parent, key, label):
        colors = self.ui_colors
        row = tk.Frame(
            parent,
            bg=colors["sidebar"],
            highlightbackground=colors["sidebar"],
            highlightthickness=1,
            height=62,
        )
        row.grid_propagate(False)
        row.rowconfigure(0, weight=1)
        row.columnconfigure(2, weight=1)
        strip = tk.Frame(row, bg=colors["sidebar"], width=3)
        strip.grid(row=0, column=0, sticky="nsw")
        icon = self.create_icon_canvas(row, key if key != "hotkeys" else "settings", size=34, fg="#d7dee9", bg=colors["sidebar"])
        icon.grid(row=0, column=1, sticky="", padx=(20, 12))
        text = tk.Label(row, text=label, bg=colors["sidebar"], fg="#d7dee9", font=("Segoe UI", 12), anchor="w")
        text.grid(row=0, column=2, sticky="nsew", padx=(0, 18))

        def enter(_event, page_key=key):
            if getattr(self, "active_page", "") != page_key:
                for widget in (row, icon, text):
                    try:
                        widget.configure(bg=colors["panel_2"])
                    except tk.TclError:
                        pass
                text.configure(fg=colors["text"])
                self.set_icon_colors(icon, colors["accent"], colors["panel_2"])

        def leave(_event, page_key=key):
            if getattr(self, "active_page", "") != page_key:
                inactive_bg = colors["panel"] if page_key == "hotkeys" else colors["sidebar"]
                for widget in (row, icon, text):
                    try:
                        widget.configure(bg=inactive_bg)
                    except tk.TclError:
                        pass
                text.configure(fg="#d7dee9")
                self.set_icon_colors(icon, "#d7dee9", inactive_bg)

        for widget in (row, strip, icon, text):
            widget.bind("<Enter>", enter, add="+")
            widget.bind("<Leave>", leave, add="+")
        self.nav_buttons[key] = {"row": row, "strip": strip, "icon": icon, "label": text}
        self.bind_click_tree(row, lambda page_key=key: self.show_main_page(page_key))
        return row

    def build_ui(self):
        root = self.root
        self.root.minsize(1180, 780)
        self.configure_dark_theme()
        colors = self.ui_colors
        root.configure(bg=colors["bg"])
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.rowconfigure(1, weight=0)

        shell = tk.Frame(root, bg=colors["bg"])
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)

        sidebar = tk.Frame(shell, bg=colors["sidebar"], width=290, highlightbackground=colors["border_soft"], highlightthickness=1)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        self.nav_buttons = {}
        nav_items = [
            ("home", "Home"),
            ("clips", "Clips"),
            ("capture", "Capture"),
            ("video", "Video"),
            ("audio", "Audio"),
            ("hud", "HUD"),
            ("storage", "Storage"),
            ("updates", "Updates"),
            ("logs", "Logs"),
        ]
        nav = tk.Frame(sidebar, bg=colors["sidebar"])
        nav.grid(row=0, column=0, sticky="ew", padx=18, pady=(20, 0))
        nav.columnconfigure(0, weight=1)
        for index, (key, label) in enumerate(nav_items):
            self.create_nav_button(nav, key, label).grid(row=index, column=0, sticky="ew", pady=(0, 8))

        sidebar_footer = tk.Frame(sidebar, bg=colors["sidebar"])
        sidebar_footer.grid(row=1, column=0, sticky="sew", padx=18, pady=(0, 18))
        sidebar_footer.columnconfigure(0, weight=1)
        sidebar.rowconfigure(1, weight=1)
        settings_row = self.create_nav_button(sidebar_footer, "hotkeys", "Settings")
        settings_row.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        status_card = self.dashboard_panel(sidebar_footer, bg=colors["panel"])
        status_card.grid(row=1, column=0, sticky="ew")
        status_card.columnconfigure(1, weight=1)
        tk.Label(status_card, text="\u25cf", bg=colors["panel"], fg=colors["accent"], font=("Segoe UI", 15)).grid(row=0, column=0, rowspan=2, padx=(16, 10), pady=15)
        tk.Label(status_card, text=APP_NAME, bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 10, "bold"), anchor="w").grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=(15, 0))
        self.sidebar_update_label = tk.Label(status_card, text="Up to date", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        self.sidebar_update_label.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(0, 15))

        main = tk.Frame(shell, bg=colors["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        self.page_container = tk.Frame(main, bg=colors["bg"])
        self.page_container.grid(row=0, column=0, sticky="nsew")
        self.page_container.columnconfigure(0, weight=1)
        self.page_container.rowconfigure(0, weight=1)
        self.pages = {}

        builders = {
            "home": self.build_home_page,
            "clips": self.build_clips_page,
            "capture": self.build_capture_page,
            "video": self.build_video_page,
            "audio": self.build_audio_page,
            "hud": self.build_hud_page,
            "hotkeys": self.build_hotkeys_page,
            "storage": self.build_storage_page,
            "updates": self.build_updates_page,
            "logs": self.build_logs_page,
        }
        for key, builder in builders.items():
            page = tk.Frame(self.page_container, bg=colors["bg"])
            page.grid(row=0, column=0, sticky="nsew", padx=26, pady=28)
            page.columnconfigure(0, weight=1)
            self.pages[key] = page
            builder(page)

        bottom = tk.Frame(root, bg=colors["bg_soft"], height=58, highlightbackground=colors["border_soft"], highlightthickness=1)
        bottom.grid(row=1, column=0, sticky="ew")
        bottom.grid_propagate(False)
        bottom.columnconfigure(0, weight=1)
        left_status = tk.Frame(bottom, bg=colors["bg_soft"])
        left_status.grid(row=0, column=0, sticky="w", padx=30)
        tk.Label(left_status, text="\u25cf", bg=colors["bg_soft"], fg=colors["accent"], font=("Segoe UI", 14)).pack(side="left", pady=18)
        self.bottom_status_label = tk.Label(left_status, text="All systems operational", bg=colors["bg_soft"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        self.bottom_status_label.pack(side="left", padx=(12, 0), pady=18)
        right_status = tk.Frame(bottom, bg=colors["bg_soft"])
        right_status.grid(row=0, column=1, sticky="e", padx=30)
        update_icon = self.icon_image("replay", 18, colors["muted"])
        self.status_update_button = tk.Button(
            right_status,
            text="Check for updates",
            command=self.check_for_updates,
            bg=colors["bg_soft"],
            fg=colors["muted"],
            activebackground=colors["panel_2"],
            activeforeground=colors["text"],
            image=update_icon,
            compound="left",
            relief="flat",
            bd=0,
            padx=14,
            pady=12,
            font=("Segoe UI", 10),
            cursor="hand2",
        )
        if update_icon:
            self.status_update_button._shadowclip_icon_ref = update_icon
        self.status_update_button.pack(side="left", padx=(0, 18))
        tk.Frame(right_status, bg=colors["border_soft"], width=1, height=24).pack(side="left", pady=16)
        self.bottom_version_label = tk.Label(right_status, text=f"v{APP_VERSION}", bg=colors["bg_soft"], fg=colors["muted"], font=("Segoe UI", 10))
        self.bottom_version_label.pack(side="left", padx=24, pady=18)
        tk.Label(right_status, text="\u22ee", bg=colors["bg_soft"], fg=colors["muted"], font=("Segoe UI", 18)).pack(side="left", pady=15)

        self.show_main_page("home")
        self.refresh_status_panel()

    def build_status_cards(self, parent):
        cards = [
            ("Replay", self.replay_status_var),
            ("Recording", self.recording_status_var),
            ("Audio", self.audio_status_var),
            ("Source", self.source_status_var),
            ("Storage", self.storage_status_var),
        ]
        for col, (title, variable) in enumerate(cards):
            card = self.create_card(parent)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 7, 0 if col == len(cards) - 1 else 7))
            tk.Label(card, text=title.upper(), bg=self.ui_colors["panel"], fg=self.ui_colors["muted"], font=("Segoe UI", 8, "bold"), anchor="center").pack(fill="x", padx=10, pady=(10, 2))
            tk.Label(card, textvariable=variable, bg=self.ui_colors["panel"], fg=self.ui_colors["text"], font=("Segoe UI", 10, "bold"), anchor="center").pack(fill="x", padx=10, pady=(0, 10))

    def build_home_page(self, parent):
        colors = self.ui_colors
        parent.rowconfigure(0, weight=1)
        content = self.create_scrollable_settings_content(parent, row=0)
        content.columnconfigure(0, weight=1)
        parent = content
        parent.rowconfigure(4, weight=1)

        header = tk.Frame(parent, bg=colors["bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 26))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="Home", bg=colors["bg"], fg=colors["text"], font=("Segoe UI", 20, "bold"), anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="Overview and quick actions", bg=colors["bg"], fg=colors["muted"], font=("Segoe UI", 11), anchor="w").grid(row=1, column=0, sticky="ew", pady=(2, 0))

        metrics = tk.Frame(parent, bg=colors["bg"])
        metrics.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        for col in range(5):
            metrics.columnconfigure(col, weight=1, uniform="metrics")
        self.home_replay_card = self.make_metric_card(
            metrics,
            "replay",
            "Replay",
            "home_replay_value",
            "home_replay_detail",
            active=True,
            command=self.toggle_replay,
        )
        self.home_replay_card.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        self.make_metric_card(metrics, "record", "Recording", "home_recording_value", "home_recording_detail").grid(row=0, column=1, sticky="nsew", padx=9)
        self.make_metric_card(metrics, "encoder", "Encoder", "home_encoder_value", "home_encoder_detail", active=True).grid(row=0, column=2, sticky="nsew", padx=9)
        self.make_metric_card(metrics, "timer", "Clip Length", "home_clip_value", "home_clip_detail", active=True).grid(row=0, column=3, sticky="nsew", padx=9)
        self.make_metric_card(metrics, "wave", "Audio", "home_audio_value", "home_audio_detail", active=True).grid(row=0, column=4, sticky="nsew", padx=(9, 0))

        actions = tk.Frame(parent, bg=colors["bg"])
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 20))
        for col in range(3):
            actions.columnconfigure(col, weight=1, uniform="actions")
        self.home_save_clip_card = self.make_action_card(actions, "clip_save", "Save Clip", f"Save the last {int(self.vars['clip_seconds'].get() or 0)} seconds", self.save_clip)
        self.home_save_clip_card.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        self.home_recording_card = self.make_action_card(actions, "record", "Start Recording", "Start a new recording", self.toggle_recording)
        self.home_recording_card.grid(row=0, column=1, sticky="nsew", padx=9)
        self.make_action_card(actions, "gallery", "Open Gallery", "View and manage clips", lambda: self.show_main_page("clips")).grid(row=0, column=2, sticky="nsew", padx=(9, 0))

        details = tk.Frame(parent, bg=colors["bg"])
        details.grid(row=3, column=0, sticky="nsew", pady=(0, 20))
        details.columnconfigure(0, weight=5, uniform="details")
        details.columnconfigure(1, weight=3, uniform="details")
        details.columnconfigure(2, weight=2, uniform="details")

        last_clip = self.dashboard_panel(details)
        last_clip.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        last_clip.columnconfigure(0, weight=3)
        last_clip.columnconfigure(1, weight=2)
        tk.Label(last_clip, text="Last Clip", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 12, "bold"), anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(20, 14))
        preview = tk.Canvas(last_clip, bg="#090d13", height=188, highlightthickness=1, highlightbackground=colors["border_soft"], bd=0)
        preview.grid(row=1, column=0, sticky="nsew", padx=(20, 14), pady=(0, 16))
        preview.configure(cursor="hand2")
        preview.bind("<Button-1>", lambda _event: self.open_last_clip(), add="+")
        preview.bind("<Configure>", lambda _event: self.render_last_clip_preview(), add="+")
        self.home_last_clip_preview = preview
        self.draw_last_clip_placeholder()
        info = tk.Frame(last_clip, bg=colors["panel"])
        info.grid(row=1, column=1, sticky="nsew", padx=(0, 20), pady=(4, 16))
        self.home_last_clip_title = tk.Label(info, text="", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 12, "bold"), anchor="w")
        self.home_last_clip_title.pack(fill="x", pady=(6, 1))
        self.home_last_clip_modified = tk.Label(info, text="", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        self.home_last_clip_modified.pack(fill="x", pady=(0, 18))
        self.home_last_clip_duration = tk.Label(info, text="", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        self.home_last_clip_duration.pack(fill="x", pady=4)
        self.home_last_clip_resolution = tk.Label(info, text="", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        self.home_last_clip_resolution.pack(fill="x", pady=4)
        self.home_last_clip_size = tk.Label(info, text="", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        self.home_last_clip_size.pack(fill="x", pady=4)
        buttons = tk.Frame(last_clip, bg=colors["panel"])
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 18))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)
        buttons.columnconfigure(3, weight=0)
        self.small_action_button(buttons, "Open", self.open_last_clip, icon_key="open").grid(row=0, column=0, sticky="ew", padx=(0, 7))
        self.small_action_button(buttons, "Edit", self.edit_last_clip, icon_key="video").grid(row=0, column=1, sticky="ew", padx=7)
        self.small_action_button(buttons, "Show", self.show_last_clip, icon_key="folder").grid(row=0, column=2, sticky="ew", padx=7)
        self.small_action_button(buttons, self.dashboard_icon("more"), self.open_output).grid(row=0, column=3, sticky="ew", padx=(7, 0))

        storage = self.dashboard_panel(details)
        storage.grid(row=0, column=1, sticky="nsew", padx=9)
        storage.columnconfigure(0, weight=1)
        tk.Label(storage, text="Storage", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 12, "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 24))
        tk.Label(storage, text="Output Folder", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w").grid(row=1, column=0, sticky="ew", padx=22)
        self.home_storage_path = tk.Label(storage, text="", bg=colors["panel"], fg=colors["accent"], font=("Segoe UI", 11), anchor="w")
        self.home_storage_path.grid(row=2, column=0, sticky="ew", padx=22, pady=(2, 22))
        self.small_action_button(storage, "", self.open_output, icon_key="folder").grid(row=1, column=1, rowspan=2, sticky="n", padx=(0, 22), pady=(0, 12))
        usage_row = tk.Frame(storage, bg=colors["panel"])
        usage_row.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22)
        usage_row.columnconfigure(0, weight=1)
        tk.Label(usage_row, text="Usage", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w").grid(row=0, column=0, sticky="w")
        self.home_storage_free = tk.Label(usage_row, text="", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="e")
        self.home_storage_free.grid(row=0, column=1, sticky="e")
        self.home_storage_canvas = tk.Canvas(storage, bg=colors["panel"], height=14, highlightthickness=0, bd=0)
        self.home_storage_canvas.grid(row=4, column=0, columnspan=2, sticky="ew", padx=22, pady=(8, 6))
        self.home_storage_percent = 0
        self.home_storage_canvas.bind("<Configure>", lambda _event: self.draw_home_storage_progress())
        self.home_storage_caption = tk.Label(storage, text="", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        self.home_storage_caption.grid(row=5, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 26))
        self.small_action_button(storage, "Clean Storage", self.clean_storage_now, icon_key="trash").grid(row=6, column=0, columnspan=2, sticky="ew", padx=22, pady=(8, 20))

        obs = self.dashboard_panel(details)
        obs.grid(row=0, column=2, sticky="nsew", padx=(9, 0))
        obs.columnconfigure(0, weight=1)
        tk.Label(obs, text="OBS Status", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 12, "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 24))
        logo = tk.Frame(obs, bg=colors["panel"], width=96, height=96)
        logo.grid(row=1, column=0, sticky="", pady=(0, 8))
        logo.grid_propagate(False)
        tk.Label(logo, text="OBS", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 24, "bold")).place(relx=0.5, rely=0.48, anchor="center")
        check_icon = self.icon_image("check", 18, "#071007")
        check_badge = tk.Label(logo, text="" if check_icon else self.dashboard_icon("check"), image=check_icon, bg=colors["accent"], fg="#071007", font=("Segoe UI", 11, "bold"), width=24, height=24)
        if check_icon:
            check_badge._shadowclip_icon_ref = check_icon
        check_badge.place(relx=0.78, rely=0.78, anchor="center")
        self.home_obs_version = tk.Label(obs, text="OBS bundled", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 11), anchor="center")
        self.home_obs_version.grid(row=2, column=0, sticky="ew")
        self.home_obs_websocket = tk.Label(obs, text="obs-websocket ready", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10), anchor="center")
        self.home_obs_websocket.grid(row=3, column=0, sticky="ew", pady=(4, 24))
        self.small_action_button(obs, "Check Setup", self.run_health_check).grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 20))

        logs = self.dashboard_panel(parent)
        logs.grid(row=4, column=0, sticky="ew")
        logs.columnconfigure(0, weight=1)
        log_header = tk.Frame(logs, bg=colors["panel"])
        log_header.grid(row=0, column=0, columnspan=3, sticky="ew")
        log_header.columnconfigure(0, weight=1)
        tk.Label(log_header, text="Recent Logs", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 12, "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=18)
        tk.Label(log_header, text="\u2304", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 18)).grid(row=0, column=1, padx=20)
        self.home_recent_logs = tk.Label(logs, text="", bg="#10151d", fg="#cbd4e0", font=("Consolas", 9), anchor="w", justify="left")
        self.home_recent_logs.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 16))
        self.small_action_button(logs, "Open Full Log", lambda: self.show_main_page("logs")).grid(row=1, column=1, sticky="e", padx=(0, 10), pady=(0, 16))
        self.small_action_button(logs, "Clear", self.clear_log_view).grid(row=1, column=2, sticky="e", padx=(0, 20), pady=(0, 16))

    def short_encoder_label(self):
        encoder = normalize_video_encoder(getattr(self.manager, "encoder_cache", "") or self.vars["video_encoder"].get())
        if encoder == "h264_nvenc":
            return "NVENC"
        if encoder == "h264_amf":
            return "AMF"
        if encoder == "h264_qsv":
            return "QSV"
        if encoder == "libx264":
            return "x264"
        return "Auto"

    def draw_home_storage_progress(self):
        canvas = getattr(self, "home_storage_canvas", None)
        if not canvas:
            return
        try:
            width = max(120, canvas.winfo_width())
            height = max(8, canvas.winfo_height())
            percent = max(0, min(1, float(getattr(self, "home_storage_percent", 0))))
            canvas.delete("all")
            canvas.create_rectangle(0, 3, width, height - 3, fill="#353d49", outline="")
            canvas.create_rectangle(0, 3, max(4, int(width * percent)), height - 3, fill=self.ui_colors["accent"], outline="")
        except (tk.TclError, ValueError, TypeError):
            pass

    def draw_last_clip_placeholder(self, message="No preview yet"):
        canvas = getattr(self, "home_last_clip_preview", None)
        if not canvas:
            return
        try:
            width = max(360, canvas.winfo_width())
            height = max(160, canvas.winfo_height())
            canvas.delete("all")
            canvas.configure(bg="#090d13")
            canvas.create_rectangle(0, 0, width, height, fill="#090d13", outline="")
            base_y = max(72, height - 48)
            canvas.create_polygon(
                width * 0.16,
                base_y,
                width * 0.34,
                height * 0.33,
                width * 0.50,
                base_y,
                fill="#2c3441",
                outline="",
            )
            canvas.create_polygon(
                width * 0.39,
                base_y,
                width * 0.55,
                height * 0.47,
                width * 0.69,
                base_y,
                fill="#343d4b",
                outline="",
            )
            canvas.create_oval(width * 0.62, height * 0.20, width * 0.68, height * 0.35, fill="#27303b", outline="")
            if message:
                canvas.create_text(
                    width / 2,
                    height - 20,
                    text=message,
                    fill=self.ui_colors["muted"],
                    font=("Segoe UI", 10),
                    anchor="center",
                )
        except tk.TclError:
            pass

    def last_clip_thumbnail_dir(self):
        path = self.manager.runtime_dir / "thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_thumbnail_cache(self, keep=80):
        try:
            files = [path for path in self.last_clip_thumbnail_dir().glob("*.png") if path.is_file()]
            files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            for path in files[keep:]:
                try:
                    path.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def thumbnail_signature_for_clip(self, clip, width, height):
        try:
            stat = Path(clip).stat()
            modified = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
            size = stat.st_size
        except OSError:
            modified = 0
            size = 0
        return (str(Path(clip).resolve()), modified, size, int(width), int(height))

    def thumbnail_path_for_signature(self, signature):
        digest = hashlib.sha1("|".join(str(part) for part in signature).encode("utf-8", errors="ignore")).hexdigest()
        return self.last_clip_thumbnail_dir() / f"{digest}.png"

    def draw_last_clip_preview_image(self, image_path, signature):
        canvas = getattr(self, "home_last_clip_preview", None)
        if not canvas:
            return
        try:
            image = tk.PhotoImage(file=str(image_path))
            width = max(1, canvas.winfo_width())
            height = max(1, canvas.winfo_height())
            canvas.delete("all")
            canvas.configure(bg="#090d13")
            canvas.create_image(width // 2, height // 2, image=image, anchor="center")
            canvas.create_polygon(20, height - 42, 20, height - 20, 39, height - 31, fill=self.ui_colors["accent"], outline="")
            canvas.create_text(
                50,
                height - 31,
                text="Open last clip",
                fill="#d7dee9",
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            )
            self.home_last_clip_preview_image = image
            self.home_last_clip_preview_signature = signature
        except tk.TclError:
            self.draw_last_clip_placeholder("Preview unavailable")

    def finish_last_clip_thumbnail(self, request_id, signature, thumbnail_path, error=None):
        if request_id != getattr(self, "home_last_clip_preview_request_id", 0):
            return
        self.home_last_clip_preview_pending = None
        if error:
            self.draw_last_clip_placeholder("Preview unavailable")
            return
        if Path(thumbnail_path).exists():
            self.draw_last_clip_preview_image(thumbnail_path, signature)
            self.cleanup_thumbnail_cache()
        else:
            self.draw_last_clip_placeholder("Preview unavailable")

    def create_video_thumbnail(self, clip, thumbnail_path, width, height, seek_seconds=None):
        ffmpeg = self.manager.find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("FFmpeg not found")
        thumbnail_path = Path(thumbnail_path)
        temp_path = thumbnail_path.with_name(f"{thumbnail_path.stem}.{uuid.uuid4().hex}.tmp.png")
        vf = (
            f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease,"
            f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:color=0x090d13"
        )
        last_error = ""
        try:
            if seek_seconds is None:
                seek_options = (1.0, 0.1)
            else:
                seek_options = (max(0.0, float(seek_seconds)),)
            for seek_seconds_value in seek_options:
                if temp_path.exists():
                    temp_path.unlink()
                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{seek_seconds_value:.3f}",
                    "-i",
                    str(clip),
                    "-frames:v",
                    "1",
                    "-vf",
                    vf,
                    "-update",
                    "1",
                    str(temp_path),
                ]
                result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=18, creationflags=CREATE_NO_WINDOW)
                if result.returncode == 0 and temp_path.exists():
                    os.replace(str(temp_path), str(thumbnail_path))
                    return
                last_error = (result.stderr or "").strip()
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        raise RuntimeError(last_error or "thumbnail generation failed")

    def generate_last_clip_thumbnail_worker(self, request_id, signature, clip, thumbnail_path, width, height):
        error = None
        try:
            self.create_video_thumbnail(clip, thumbnail_path, width, height)
        except Exception as exc:
            error = str(exc)
        if getattr(self, "is_quitting", False):
            return
        try:
            self.root.after(0, lambda: self.finish_last_clip_thumbnail(request_id, signature, thumbnail_path, error))
        except (tk.TclError, RuntimeError):
            pass

    def render_last_clip_preview(self):
        canvas = getattr(self, "home_last_clip_preview", None)
        if not canvas:
            return
        clip = self.manager.latest_clip_path()
        if not clip or not Path(clip).exists():
            self.home_last_clip_preview_signature = None
            self.home_last_clip_preview_pending = None
            self.home_last_clip_preview_image = None
            self.draw_last_clip_placeholder()
            return
        try:
            width = max(240, int(canvas.winfo_width()))
            height = max(120, int(canvas.winfo_height()))
        except tk.TclError:
            return
        if width <= 240 and height <= 120:
            self.root.after(120, self.render_last_clip_preview)
            return
        signature = self.thumbnail_signature_for_clip(clip, width, height)
        if signature == getattr(self, "home_last_clip_preview_signature", None):
            return
        thumbnail_path = self.thumbnail_path_for_signature(signature)
        if thumbnail_path.exists():
            self.draw_last_clip_preview_image(thumbnail_path, signature)
            return
        if signature == getattr(self, "home_last_clip_preview_pending", None):
            return
        self.home_last_clip_preview_pending = signature
        self.home_last_clip_preview_request_id += 1
        request_id = self.home_last_clip_preview_request_id
        self.draw_last_clip_placeholder("Generating preview...")
        thread = threading.Thread(
            target=self.generate_last_clip_thumbnail_worker,
            args=(request_id, signature, Path(clip), thumbnail_path, width, height),
            daemon=True,
        )
        thread.start()

    def update_recent_logs_preview(self):
        widget = getattr(self, "home_recent_logs", None)
        if not widget:
            return
        lines = self.recent_log_lines[-2:]
        if not lines:
            lines = ["Ready. Waiting for ShadowClip events."]
        try:
            widget.configure(text="\n".join(lines))
        except tk.TclError:
            pass

    def update_status_bar(self):
        status = getattr(self, "status_var", None)
        text = status.get() if status else "All systems operational"
        if not text or text == "Ready" or "error" not in text.casefold() and "failed" not in text.casefold():
            text = "All systems operational"
        self.set_label_text("bottom_status_label", text)
        if getattr(self, "pending_update", None):
            self.set_label_text("sidebar_update_label", "Update available")
        else:
            self.set_label_text("sidebar_update_label", "Up to date")

    def update_home_dashboard(self):
        colors = self.ui_colors
        replay_running = self.replay_running()
        recording_running = self.recording_running()
        self.set_label_text("home_replay_value", "Running" if replay_running else "Idle", colors["accent"] if replay_running else colors["text"])
        replay_action = "Stop" if replay_running else "Start"
        self.set_label_text(
            "home_replay_detail",
            replay_action,
            colors["accent"] if replay_running else colors["muted"],
        )
        self.set_label_text("home_recording_value", "Recording" if recording_running else "Idle", colors["accent"] if recording_running else colors["text"])
        self.set_label_text("home_recording_detail", self.recording_detail_label() if recording_running else "\u25cf  Ready", colors["accent"] if recording_running else colors["muted"])
        self.set_label_text("home_encoder_value", self.short_encoder_label(), colors["accent"])
        self.set_label_text("home_encoder_detail", "Hardware (H.264)" if self.short_encoder_label() in {"NVENC", "AMF", "QSV"} else video_encoder_label(self.vars["video_encoder"].get()))
        clip_seconds = int(self.vars["clip_seconds"].get() or 0)
        self.set_label_text("home_clip_value", f"{clip_seconds}s", colors["accent"])
        self.set_label_text("home_clip_detail", f"Auto RAM: {int(self.vars['obs_replay_buffer_mb'].get() or 0)} MB")
        audio_parts = []
        if bool(self.vars["mic_enabled"].get()):
            audio_parts.append("Mic")
        if bool(self.vars["desktop_audio_enabled"].get()):
            audio_parts.append("Desktop")
        self.set_label_text("home_audio_value", "OK" if audio_parts else "Off", colors["accent"] if audio_parts else colors["text"])
        self.set_label_text("home_audio_detail", " + ".join(audio_parts) if audio_parts else "No audio")

        clip_info = self.latest_clip_dashboard_info()
        self.set_label_text("home_last_clip_title", clip_info["title"])
        self.set_label_text("home_last_clip_modified", clip_info["modified"])
        self.set_label_text("home_last_clip_duration", f"\u25f7  {clip_info['duration']}")
        self.set_label_text("home_last_clip_resolution", f"\u25ad  {clip_info['resolution']}" if clip_info["resolution"] else "")
        self.set_label_text("home_last_clip_size", f"\u25ab  {clip_info['size']}" if clip_info["size"] else "")
        self.render_last_clip_preview()

        output_dir, free_text, caption, percent = self.storage_dashboard_info()
        self.set_label_text("home_storage_path", self.compact_path_label(output_dir))
        self.set_label_text("home_storage_free", free_text)
        self.set_label_text("home_storage_caption", caption)
        self.home_storage_percent = percent
        self.draw_home_storage_progress()

        backend = self.vars["capture_backend"].get()
        self.set_label_text("home_obs_version", "OBS backend" if backend == "obs" else f"Backend: {backend}")
        self.set_label_text("home_obs_websocket", f"websocket :{int(self.config.get('obs_websocket_port', 4457) or 4457)}")
        self.update_recent_logs_preview()
        self.update_status_bar()

    def clear_log_view(self):
        self.recent_log_lines = []
        if hasattr(self, "log_text"):
            try:
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.configure(state="disabled")
            except tk.TclError:
                pass
        self.update_recent_logs_preview()

    def build_clips_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        header = tk.Frame(parent, bg=colors["bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="Clips", bg=colors["bg"], fg=colors["text"], font=("Segoe UI", 20, "bold"), anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="Browse, filter, and manage your replays and recordings", bg=colors["bg"], fg=colors["muted"], font=("Segoe UI", 11), anchor="w").grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.small_action_button(header, "Open folder", self.open_output, icon_key="folder").grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 8))
        self.small_action_button(header, "Refresh", lambda: self.refresh_clip_library(force=True), icon_key="replay").grid(row=0, column=2, rowspan=2, sticky="e")

        toolbar = self.dashboard_panel(parent)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        toolbar.columnconfigure(0, weight=2)
        toolbar.columnconfigure(1, weight=1)
        toolbar.columnconfigure(2, weight=1)
        toolbar.columnconfigure(3, weight=1)
        search_box = tk.Frame(toolbar, bg=colors["panel_2"], highlightbackground=colors["border"], highlightthickness=1)
        search_box.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=15)
        search_icon = self.create_icon_canvas(search_box, "clips", size=20, fg=colors["muted"], bg=colors["panel_2"])
        search_icon.pack(side="left", padx=(10, 6), pady=7)
        self.clip_search_entry = tk.Entry(
            search_box,
            textvariable=self.clip_search_var,
            bg=colors["panel_2"],
            fg=colors["text"],
            insertbackground=colors["text"],
            relief="flat",
            bd=0,
            font=("Segoe UI", 10),
        )
        self.clip_search_entry.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=7)
        self.clip_search_entry.bind("<FocusIn>", self.on_clip_search_focus_in, add="+")
        self.clip_search_entry.bind("<FocusOut>", self.on_clip_search_focus_out, add="+")
        self.set_clip_search_placeholder()
        self.clip_game_filter = ttk.Combobox(toolbar, state="readonly", style="Gallery.TCombobox", textvariable=self.clip_game_filter_var, values=["All games/apps"])
        self.clip_game_filter.grid(row=0, column=1, sticky="ew", padx=8, pady=15)
        self.clip_kind_filter = ttk.Combobox(toolbar, state="readonly", style="Gallery.TCombobox", textvariable=self.clip_kind_filter_var, values=["All media", "Replay clips", "Recordings"])
        self.clip_kind_filter.grid(row=0, column=2, sticky="ew", padx=8, pady=15)
        self.clip_sort = ttk.Combobox(toolbar, state="readonly", style="Gallery.TCombobox", textvariable=self.clip_sort_var, values=["Newest first", "Oldest first", "Name A-Z", "Largest first"])
        self.clip_sort.grid(row=0, column=3, sticky="ew", padx=(8, 16), pady=15)

        gallery = tk.Frame(parent, bg=colors["bg"])
        gallery.grid(row=2, column=0, sticky="nsew")
        gallery.columnconfigure(0, weight=1)
        gallery.rowconfigure(1, weight=1)
        self.clip_library_summary = tk.Label(gallery, text="Scanning clip library...", bg=colors["bg"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
        self.clip_library_summary.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        viewport = tk.Frame(gallery, bg=colors["bg"])
        viewport.grid(row=1, column=0, sticky="nsew")
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        self.clip_gallery_canvas = tk.Canvas(viewport, bg=colors["bg"], highlightthickness=0, bd=0)
        self.clip_gallery_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.clip_gallery_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self.clip_gallery_canvas.configure(yscrollcommand=scrollbar.set)
        self.clip_gallery_grid = tk.Frame(self.clip_gallery_canvas, bg=colors["bg"])
        self.clip_gallery_window = self.clip_gallery_canvas.create_window((0, 0), window=self.clip_gallery_grid, anchor="nw")
        self.clip_gallery_grid.bind("<Configure>", self.on_clip_gallery_grid_configure, add="+")
        self.clip_gallery_canvas.bind("<Configure>", self.on_clip_gallery_canvas_configure, add="+")
        self.clip_gallery_canvas.bind("<MouseWheel>", self.scroll_clip_gallery, add="+")

        self.clip_library_load_more = self.small_action_button(gallery, "Load more", self.load_more_clip_cards)
        self.clip_library_load_more.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.clip_library_load_more.grid_remove()

        for variable in (self.clip_search_var, self.clip_game_filter_var, self.clip_kind_filter_var, self.clip_sort_var):
            variable.trace_add("write", lambda *_args: self.schedule_clip_library_filter())
        self.root.after(350, lambda: self.refresh_clip_library(force=True))

    def set_clip_search_placeholder(self):
        if not self.clip_search_var.get():
            self.clip_search_var.set("Search clips...")
            self.clip_search_entry.configure(fg=self.ui_colors["muted"])

    def on_clip_search_focus_in(self, _event=None):
        if self.clip_search_var.get() == "Search clips...":
            self.clip_search_var.set("")
        self.clip_search_entry.configure(fg=self.ui_colors["text"])

    def on_clip_search_focus_out(self, _event=None):
        self.set_clip_search_placeholder()

    def on_clip_gallery_grid_configure(self, _event=None):
        canvas = getattr(self, "clip_gallery_canvas", None)
        if not canvas:
            return
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except tk.TclError:
            pass

    def on_clip_gallery_canvas_configure(self, event):
        canvas = getattr(self, "clip_gallery_canvas", None)
        if not canvas:
            return
        try:
            canvas.itemconfigure(self.clip_gallery_window, width=max(1, int(event.width)))
        except tk.TclError:
            return
        columns = 3 if event.width >= 1080 else 2 if event.width >= 690 else 1
        if columns != self.clip_library_columns:
            self.clip_library_columns = columns
            self.schedule_clip_library_filter(reset_limit=False)

    def scroll_clip_gallery(self, event):
        canvas = getattr(self, "clip_gallery_canvas", None)
        if not canvas:
            return "break"
        delta = int(getattr(event, "delta", 0) or 0)
        steps = -1 if delta > 0 else 1
        canvas.yview_scroll(steps * 3, "units")
        return "break"

    def bind_clip_gallery_mousewheel(self, widget):
        stack = [widget]
        while stack:
            current = stack.pop()
            current.bind("<MouseWheel>", self.scroll_clip_gallery, add="+")
            stack.extend(current.winfo_children())

    def schedule_clip_library_filter(self, reset_limit=True):
        if reset_limit:
            self.clip_library_render_limit = 24
        if self.clip_library_render_after_id:
            try:
                self.root.after_cancel(self.clip_library_render_after_id)
            except (tk.TclError, ValueError):
                pass
        self.clip_library_render_after_id = self.root.after(80, self.apply_clip_library_filters)

    def refresh_clip_library(self, force=False):
        if self.clip_library_scan_running:
            if force:
                self.clip_library_refresh_pending = True
            return
        if not force and self.clip_library_items and time.time() - self.clip_library_last_scan_at < 4:
            self.apply_clip_library_filters()
            return
        output_dir = expand_path(self.output_path_label())
        self.clip_library_scan_running = True
        self.clip_library_scan_id += 1
        scan_id = self.clip_library_scan_id
        if hasattr(self, "clip_library_summary"):
            self.clip_library_summary.configure(text="Scanning clip library...")
        thread = threading.Thread(target=self.scan_clip_library_worker, args=(scan_id, output_dir), daemon=True)
        thread.start()

    def scan_clip_library_worker(self, scan_id, output_dir):
        items = []
        root = Path(output_dir)
        try:
            if root.exists():
                for path in root.rglob("*"):
                    if not path.is_file() or path.suffix.casefold() not in MEDIA_EXTENSIONS:
                        continue
                    try:
                        stat = path.stat()
                        relative = path.relative_to(root)
                    except (OSError, ValueError):
                        continue
                    raw_app_name = relative.parts[0] if len(relative.parts) > 1 else "Unsorted"
                    app_name = friendly_application_name(raw_app_name, "", raw_app_name)
                    items.append({
                        "path": path,
                        "path_key": str(path.resolve()).casefold(),
                        "title": path.stem,
                        "app": app_name,
                        "kind": media_kind_for_path(path),
                        "size": int(stat.st_size),
                        "modified": float(stat.st_mtime),
                    })
        except OSError:
            pass
        items.sort(key=lambda item: item["modified"], reverse=True)
        if self.is_quitting:
            return
        try:
            self.root.after(0, lambda: self.finish_clip_library_scan(scan_id, items))
        except (tk.TclError, RuntimeError):
            pass

    def finish_clip_library_scan(self, scan_id, items):
        if scan_id != self.clip_library_scan_id:
            return
        self.clip_library_scan_running = False
        self.clip_library_last_scan_at = time.time()
        self.clip_library_items = items
        apps = sorted({item["app"] for item in items}, key=str.casefold)
        values = ["All games/apps", *apps]
        if hasattr(self, "clip_game_filter"):
            self.clip_game_filter.configure(values=values)
        if self.clip_game_filter_var.get() not in values:
            self.clip_game_filter_var.set("All games/apps")
        self.apply_clip_library_filters()
        if self.clip_library_refresh_pending:
            self.clip_library_refresh_pending = False
            self.root.after(80, lambda: self.refresh_clip_library(force=True))

    def apply_clip_library_filters(self):
        self.clip_library_render_after_id = None
        query = self.clip_search_var.get().strip().casefold()
        if query == "search clips...":
            query = ""
        selected_app = self.clip_game_filter_var.get()
        selected_kind = self.clip_kind_filter_var.get()
        items = []
        for item in self.clip_library_items:
            if selected_app != "All games/apps" and item["app"] != selected_app:
                continue
            if selected_kind == "Replay clips" and item["kind"] != "replay":
                continue
            if selected_kind == "Recordings" and item["kind"] != "recording":
                continue
            haystack = f"{item['title']} {item['app']} {item['path'].name}".casefold()
            if query and query not in haystack:
                continue
            items.append(item)
        sort_mode = self.clip_sort_var.get()
        if sort_mode == "Oldest first":
            items.sort(key=lambda item: item["modified"])
        elif sort_mode == "Name A-Z":
            items.sort(key=lambda item: (item["title"].casefold(), -item["modified"]))
        elif sort_mode == "Largest first":
            items.sort(key=lambda item: item["size"], reverse=True)
        else:
            items.sort(key=lambda item: item["modified"], reverse=True)
        self.clip_library_filtered = items
        self.render_clip_library()

    def clip_library_summary_text(self, visible_count):
        total = len(self.clip_library_items)
        matched = len(self.clip_library_filtered)
        apps = len({item["app"] for item in self.clip_library_items})
        if matched == total:
            return f"{total} media file{'s' if total != 1 else ''} across {apps} game/app folder{'s' if apps != 1 else ''}"
        return f"Showing {visible_count} of {matched} matches | {total} total"

    def render_clip_library(self):
        grid = getattr(self, "clip_gallery_grid", None)
        if not grid:
            return
        for child in grid.winfo_children():
            child.destroy()
        self.clip_gallery_card_canvases = {}
        self.clip_gallery_metadata_labels = {}
        columns = max(1, self.clip_library_columns or 3)
        for column in range(columns):
            grid.columnconfigure(column, weight=1, uniform="clip_cards")
        items = self.clip_library_filtered[:self.clip_library_render_limit]
        if hasattr(self, "clip_library_summary"):
            self.clip_library_summary.configure(text=self.clip_library_summary_text(len(items)))
        if not items:
            empty = self.dashboard_panel(grid)
            empty.grid(row=0, column=0, columnspan=columns, sticky="ew", pady=(0, 12))
            icon = self.create_icon_canvas(empty, "clips", size=48, fg=self.ui_colors["muted_dark"], bg=self.ui_colors["panel"])
            icon.pack(pady=(34, 10))
            title = "No matching clips" if self.clip_library_items else "No clips or recordings yet"
            detail = "Try another search or filter." if self.clip_library_items else "Saved media will appear here automatically."
            tk.Label(empty, text=title, bg=self.ui_colors["panel"], fg=self.ui_colors["text"], font=("Segoe UI", 13, "bold")).pack()
            tk.Label(empty, text=detail, bg=self.ui_colors["panel"], fg=self.ui_colors["muted"], font=("Segoe UI", 10)).pack(pady=(5, 34))
            self.bind_clip_gallery_mousewheel(empty)
        else:
            for index, item in enumerate(items):
                row, column = divmod(index, columns)
                card = self.create_clip_library_card(grid, item)
                left = 0 if column == 0 else 8
                right = 0 if column == columns - 1 else 8
                card.grid(row=row, column=column, sticky="nsew", padx=(left, right), pady=(0, 16))
        if len(self.clip_library_filtered) > len(items):
            self.clip_library_load_more.grid()
            remaining = len(self.clip_library_filtered) - len(items)
            self.clip_library_load_more.configure(text=f"Load more ({remaining} remaining)")
        else:
            self.clip_library_load_more.grid_remove()
        try:
            self.clip_gallery_canvas.yview_moveto(0)
            self.clip_gallery_canvas.configure(scrollregion=self.clip_gallery_canvas.bbox("all"))
        except tk.TclError:
            pass

    def clip_kind_label(self, kind):
        return {"replay": "Replay", "recording": "Recording", "video": "Video"}.get(kind, "Video")

    def create_clip_library_card(self, parent, item):
        colors = self.ui_colors
        card = self.dashboard_panel(parent)
        card.columnconfigure(0, weight=1)
        preview = tk.Canvas(card, bg="#090d13", height=203, highlightthickness=0, bd=0, cursor="hand2")
        preview.grid(row=0, column=0, sticky="ew")
        preview._shadowclip_path_key = item["path_key"]
        preview._shadowclip_placeholder = "Generating preview..."
        preview.bind("<Configure>", lambda _event, canvas=preview: self.redraw_clip_card_preview(canvas), add="+")
        preview.bind("<Button-1>", lambda _event, path=item["path"]: self.play_clip_path(path), add="+")
        preview.bind("<Button-3>", lambda event, path=item["path"]: self.show_clip_library_menu(event, path), add="+")
        self.draw_clip_card_placeholder(preview, preview._shadowclip_placeholder)

        details = tk.Frame(card, bg=colors["panel"])
        details.grid(row=1, column=0, sticky="ew", padx=16, pady=(14, 10))
        details.columnconfigure(0, weight=1)
        title = tk.Label(details, text=item["title"], bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 11, "bold"), anchor="w")
        title.grid(row=0, column=0, sticky="ew")
        kind = tk.Label(details, text=self.clip_kind_label(item["kind"]), bg=colors["accent_dark"], fg=colors["accent"], font=("Segoe UI", 8, "bold"), padx=8, pady=3)
        kind.grid(row=0, column=1, sticky="e", padx=(8, 0))
        modified = datetime.fromtimestamp(item["modified"]).strftime("%d.%m.%Y  %H:%M")
        tk.Label(details, text=f"{item['app']}  |  {modified}", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9), anchor="w").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        metadata = tk.Label(details, text=f"Reading details...  |  {format_file_size(item['size'])}", bg=colors["panel"], fg=colors["muted_dark"], font=("Segoe UI", 9), anchor="w")
        metadata.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))

        actions = tk.Frame(card, bg=colors["panel"])
        actions.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 15))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        self.small_action_button(actions, "Open", lambda path=item["path"]: self.play_clip_path(path), icon_key="open").grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.small_action_button(actions, "Edit", lambda path=item["path"]: self.open_clip_editor(path), icon_key="video").grid(row=0, column=1, sticky="ew", padx=5)
        self.small_action_button(actions, "Show", lambda path=item["path"]: self.reveal_clip_path(path), icon_key="folder").grid(row=0, column=2, sticky="ew", padx=5)
        more = self.small_action_button(actions, "...", lambda path=item["path"]: self.show_clip_library_button_menu(path, more))
        more.grid(row=0, column=3, sticky="ew", padx=(5, 0))
        card.bind("<Button-3>", lambda event, path=item["path"]: self.show_clip_library_menu(event, path), add="+")
        self.bind_clip_gallery_mousewheel(card)
        self.queue_clip_gallery_media(item, preview, metadata)
        return card

    def draw_clip_card_placeholder(self, canvas, message="Generating preview..."):
        try:
            width = max(240, canvas.winfo_width())
            height = max(150, canvas.winfo_height())
            canvas.delete("all")
            canvas.create_rectangle(0, 0, width, height, fill="#090d13", outline="")
            image = self.icon_image("image", 48, self.ui_colors["muted_dark"])
            if image:
                canvas.create_image(width // 2, height // 2 - 10, image=image)
                canvas._shadowclip_placeholder_image = image
            canvas.create_text(width // 2, height - 27, text=message, fill=self.ui_colors["muted_dark"], font=("Segoe UI", 9))
        except tk.TclError:
            pass

    def redraw_clip_card_preview(self, canvas):
        image = getattr(canvas, "_shadowclip_preview_image", None)
        if image is None:
            self.draw_clip_card_placeholder(canvas, getattr(canvas, "_shadowclip_placeholder", "Generating preview..."))
            return
        try:
            width = max(1, canvas.winfo_width())
            height = max(1, canvas.winfo_height())
            canvas.delete("all")
            canvas.create_image(width // 2, height // 2, image=image)
            canvas.create_rectangle(0, height - 38, width, height, fill="#090d13", outline="", stipple="gray50")
            canvas.create_polygon(16, height - 28, 16, height - 12, 30, height - 20, fill=self.ui_colors["accent"], outline="")
            canvas.create_text(39, height - 20, text="Play clip", fill="#f4f7fb", font=("Segoe UI", 9, "bold"), anchor="w")
        except tk.TclError:
            pass

    def queue_clip_gallery_media(self, item, canvas, metadata_label):
        signature = self.thumbnail_signature_for_clip(item["path"], 360, 203)
        thumbnail_path = self.thumbnail_path_for_signature(signature)
        key = item["path_key"]
        self.clip_gallery_card_canvases[key] = (canvas, signature, thumbnail_path)
        self.clip_gallery_metadata_labels[key] = (metadata_label, signature)
        cached_metadata = self.clip_gallery_metadata_cache.get(signature[:3])
        if cached_metadata:
            metadata_label.configure(text=self.clip_gallery_metadata_text(item, cached_metadata))
        if thumbnail_path.exists():
            self.load_clip_gallery_thumbnail(key, canvas, signature, thumbnail_path)
        if signature in self.clip_gallery_thumbnail_pending:
            return
        if thumbnail_path.exists() and cached_metadata:
            return
        self.clip_gallery_thumbnail_pending.add(signature)
        self.clip_gallery_thumbnail_queue.put((item.copy(), signature, thumbnail_path))
        self.ensure_clip_gallery_thumbnail_worker()

    def ensure_clip_gallery_thumbnail_worker(self):
        worker = self.clip_gallery_thumbnail_worker
        if worker and worker.is_alive():
            return
        worker = threading.Thread(target=self.clip_gallery_media_worker, daemon=True)
        self.clip_gallery_thumbnail_worker = worker
        worker.start()

    def clip_gallery_media_worker(self):
        while not self.is_quitting:
            try:
                item, signature, thumbnail_path = self.clip_gallery_thumbnail_queue.get_nowait()
            except queue.Empty:
                return
            error = None
            metadata = {}
            try:
                if not Path(thumbnail_path).exists():
                    self.create_video_thumbnail(item["path"], thumbnail_path, 360, 203)
                metadata = self.probe_clip_library_media(item["path"])
            except Exception as exc:
                error = str(exc)
            try:
                self.root.after(0, lambda data=item, sig=signature, thumb=thumbnail_path, meta=metadata, err=error: self.finish_clip_gallery_media(data, sig, thumb, meta, err))
            except (tk.TclError, RuntimeError):
                return

    def probe_clip_library_media(self, media_path):
        ffprobe = self.manager.find_ffprobe()
        if not ffprobe:
            return {}
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height:format=duration",
                "-of", "json",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return {}
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        stream = streams[0] if streams else {}
        try:
            duration = float((payload.get("format") or {}).get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        return {
            "duration": duration,
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
        }

    def clip_gallery_metadata_text(self, item, metadata):
        parts = []
        duration = float(metadata.get("duration") or 0)
        width = int(metadata.get("width") or 0)
        height = int(metadata.get("height") or 0)
        if duration > 0:
            parts.append(format_duration(round(duration)))
        if width > 0 and height > 0:
            parts.append(f"{width}x{height}")
        parts.append(format_file_size(item["size"]))
        return "  |  ".join(parts)

    def finish_clip_gallery_media(self, item, signature, thumbnail_path, metadata, error=None):
        self.clip_gallery_thumbnail_pending.discard(signature)
        key = item["path_key"]
        if metadata:
            self.clip_gallery_metadata_cache[signature[:3]] = metadata
        label_entry = self.clip_gallery_metadata_labels.get(key)
        if label_entry and label_entry[1] == signature:
            label = label_entry[0]
            try:
                label.configure(text=self.clip_gallery_metadata_text(item, metadata))
            except tk.TclError:
                pass
        canvas_entry = self.clip_gallery_card_canvases.get(key)
        if canvas_entry and canvas_entry[1] == signature:
            canvas = canvas_entry[0]
            if Path(thumbnail_path).exists():
                self.load_clip_gallery_thumbnail(key, canvas, signature, thumbnail_path)
            elif error:
                canvas._shadowclip_placeholder = "Preview unavailable"
                self.draw_clip_card_placeholder(canvas, canvas._shadowclip_placeholder)
        self.cleanup_thumbnail_cache(keep=240)

    def load_clip_gallery_thumbnail(self, key, canvas, signature, thumbnail_path):
        try:
            image = self.clip_gallery_thumbnail_images.get(signature)
            if image is None:
                image = tk.PhotoImage(file=str(thumbnail_path))
                self.clip_gallery_thumbnail_images[signature] = image
            canvas._shadowclip_preview_image = image
            canvas._shadowclip_placeholder = ""
            self.redraw_clip_card_preview(canvas)
        except tk.TclError:
            canvas._shadowclip_placeholder = "Preview unavailable"
            self.draw_clip_card_placeholder(canvas, canvas._shadowclip_placeholder)

    def load_more_clip_cards(self):
        self.clip_library_render_limit += 24
        self.render_clip_library()

    def show_clip_library_button_menu(self, path, button):
        try:
            x = button.winfo_rootx()
            y = button.winfo_rooty() + button.winfo_height()
        except tk.TclError:
            return
        self.popup_clip_library_menu(path, x, y)

    def show_clip_library_menu(self, event, path):
        self.popup_clip_library_menu(path, event.x_root, event.y_root)
        return "break"

    def popup_clip_library_menu(self, path, x, y):
        colors = self.ui_colors
        menu = tk.Menu(self.root, tearoff=False, bg=colors["panel_2"], fg=colors["text"], activebackground=colors["accent"], activeforeground="#071007", relief="flat", bd=1)
        menu.add_command(label="Open", command=lambda: self.play_clip_path(path))
        menu.add_command(label="Edit clip", command=lambda: self.open_clip_editor(path))
        menu.add_command(label="Show in folder", command=lambda: self.reveal_clip_path(path))
        menu.add_separator()
        menu.add_command(label="Rename", command=lambda: self.rename_clip_library_path(path))
        menu.add_command(label="Move to Recycle Bin", command=lambda: self.delete_clip_library_path(path))
        try:
            menu.tk_popup(int(x), int(y))
        finally:
            menu.grab_release()

    def edit_last_clip(self):
        clip = self.manager.latest_clip_path()
        if not clip:
            self.threadsafe_log("No saved clip found yet.")
            return
        self.open_clip_editor(clip)

    def open_clip_editor(self, path):
        path = Path(path)
        if not path.exists():
            self.threadsafe_log(f"Media file no longer exists: {path}")
            self.refresh_clip_library(force=True)
            return
        if not self.manager.find_ffmpeg() or not self.manager.find_ffprobe():
            messagebox.showerror(
                APP_NAME,
                "The clip editor needs the bundled FFmpeg tools.\n\n"
                "Run Check Setup and repair FFmpeg first.",
                parent=self.root,
            )
            return

        colors = self.ui_colors
        window = tk.Toplevel(self.root)
        window.title(f"Edit clip - {path.name}")
        window.configure(bg=colors["bg"])
        window.geometry("980x720")
        window.minsize(820, 680)
        window.transient(self.root)
        state = {
            "window": window,
            "path": path,
            "duration": 0.0,
            "preview_images": {},
            "preview_after": {},
            "preview_requests": {"start": 0, "end": 0},
            "updating": False,
            "exporting": False,
            "cancel_event": threading.Event(),
        }
        window._shadowclip_editor_state = state
        loading = tk.Frame(window, bg=colors["bg"])
        loading.pack(fill="both", expand=True)
        self.create_icon_canvas(
            loading,
            "video",
            size=48,
            fg=colors["accent"],
            bg=colors["bg"],
        ).pack(pady=(180, 18))
        tk.Label(
            loading,
            text="Preparing clip editor...",
            bg=colors["bg"],
            fg=colors["text"],
            font=("Segoe UI", 16, "bold"),
        ).pack()
        tk.Label(
            loading,
            text=path.name,
            bg=colors["bg"],
            fg=colors["muted"],
            font=("Segoe UI", 10),
        ).pack(pady=(8, 0))
        state["loading"] = loading
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_clip_editor(state))

        def probe_worker():
            duration = self.manager.probe_duration(path)
            error = None if duration and duration > 0 else "Could not read the clip duration."
            try:
                self.root.after(
                    0,
                    lambda: self.finish_clip_editor_loading(state, duration or 0.0, error),
                )
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(
            target=probe_worker,
            daemon=True,
            name="ShadowClipEditorProbe",
        ).start()

    def finish_clip_editor_loading(self, state, duration, error=None):
        window = state["window"]
        if not window.winfo_exists():
            return
        if error:
            messagebox.showerror(APP_NAME, error, parent=window)
            window.destroy()
            return
        state["duration"] = float(duration)
        state["loading"].destroy()
        self.build_clip_editor(state)

    def build_clip_editor(self, state):
        colors = self.ui_colors
        window = state["window"]
        duration = state["duration"]
        root = tk.Frame(window, bg=colors["bg"])
        root.pack(fill="both", expand=True, padx=24, pady=14)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        header = tk.Frame(root, bg=colors["bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Clip editor",
            bg=colors["bg"],
            fg=colors["text"],
            font=("Segoe UI", 19, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text=state["path"].name,
            bg=colors["bg"],
            fg=colors["muted"],
            font=("Segoe UI", 10),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        tk.Label(
            header,
            text=f"Source duration  {format_precise_duration(duration)}",
            bg=colors["bg"],
            fg=colors["muted"],
            font=("Segoe UI", 10),
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        preview_row = tk.Frame(root, bg=colors["bg"])
        preview_row.grid(row=1, column=0, sticky="nsew", pady=(0, 16))
        preview_row.columnconfigure(0, weight=1, uniform="editor_preview")
        preview_row.columnconfigure(1, weight=1, uniform="editor_preview")
        for column, kind, title in ((0, "start", "Start frame"), (1, "end", "End frame")):
            panel = self.dashboard_panel(preview_row)
            panel.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0, 8) if column == 0 else (8, 0),
            )
            panel.columnconfigure(0, weight=1)
            tk.Label(
                panel,
                text=title,
                bg=colors["panel"],
                fg=colors["text"],
                font=("Segoe UI", 11, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
            canvas = tk.Canvas(
                panel,
                bg="#090d13",
                height=180,
                highlightthickness=1,
                highlightbackground=colors["border_soft"],
                bd=0,
            )
            canvas.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
            canvas.bind(
                "<Configure>",
                lambda _event, editor_state=state, preview_kind=kind: self.redraw_clip_editor_preview(
                    editor_state,
                    preview_kind,
                ),
                add="+",
            )
            state[f"{kind}_canvas"] = canvas

        controls = self.dashboard_panel(root)
        controls.grid(row=2, column=0, sticky="nsew")
        controls.columnconfigure(0, weight=1)
        start_var = tk.DoubleVar(value=0.0)
        end_var = tk.DoubleVar(value=duration)
        state["start_var"] = start_var
        state["end_var"] = end_var
        state["mode_var"] = tk.StringVar(value="fast")
        state["replace_var"] = tk.BooleanVar(value=False)
        state["start_label_var"] = tk.StringVar()
        state["end_label_var"] = tk.StringVar()
        state["selection_label_var"] = tk.StringVar()
        state["status_var"] = tk.StringVar(value="Ready to trim")
        state["progress_var"] = tk.DoubleVar(value=0.0)

        self.build_clip_editor_range_row(controls, state, "start", 0)
        self.build_clip_editor_range_row(controls, state, "end", 1)

        summary = tk.Frame(controls, bg=colors["panel"])
        summary.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 14))
        summary.columnconfigure(0, weight=1)
        tk.Label(
            summary,
            textvariable=state["selection_label_var"],
            bg=colors["panel"],
            fg=colors["accent"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        options = tk.Frame(controls, bg=colors["panel"])
        options.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 12))
        options.columnconfigure(3, weight=1)
        tk.Label(
            options,
            text="Export mode",
            bg=colors["panel"],
            fg=colors["muted"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Radiobutton(
            options,
            text="Fast and lossless",
            variable=state["mode_var"],
            value="fast",
            style="Card.TRadiobutton",
        ).grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Radiobutton(
            options,
            text="Frame accurate",
            variable=state["mode_var"],
            value="accurate",
            style="Card.TRadiobutton",
        ).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(
            options,
            text="Replace original",
            variable=state["replace_var"],
            style="Card.TCheckbutton",
        ).grid(row=0, column=4, sticky="e")
        tk.Label(
            options,
            text="Fast mode keeps the original video quality and cuts at the nearest keyframe.",
            bg=colors["panel"],
            fg=colors["muted_dark"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 0))

        progress = ttk.Progressbar(
            controls,
            variable=state["progress_var"],
            maximum=100,
            mode="determinate",
            style="Accent.Horizontal.TProgressbar",
        )
        progress.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 8))
        state["progress"] = progress
        tk.Label(
            controls,
            textvariable=state["status_var"],
            bg=colors["panel"],
            fg=colors["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 12))

        buttons = tk.Frame(controls, bg=colors["panel"])
        buttons.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 18))
        buttons.columnconfigure(0, weight=1)
        save_button = self.small_action_button(
            buttons,
            "Save trimmed copy",
            lambda: self.start_clip_editor_export(state),
            accent=True,
            icon_key="clapper",
        )
        save_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        cancel_button = self.small_action_button(
            buttons,
            "Close",
            lambda: self.close_clip_editor(state),
        )
        cancel_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        state["save_button"] = save_button
        state["cancel_button"] = cancel_button

        state["replace_var"].trace_add(
            "write",
            lambda *_args: state["save_button"].configure(
                text="Replace original"
                if state["replace_var"].get()
                else "Save trimmed copy"
            ),
        )
        self.update_clip_editor_selection(state, "start", 0.0)
        self.update_clip_editor_selection(state, "end", duration)

    def build_clip_editor_range_row(self, parent, state, kind, row):
        colors = self.ui_colors
        frame = tk.Frame(parent, bg=colors["panel"])
        frame.grid(row=row, column=0, sticky="ew", padx=18, pady=(14, 0))
        frame.columnconfigure(1, weight=1)
        label_text = "Start" if kind == "start" else "End"
        tk.Label(
            frame,
            text=label_text,
            bg=colors["panel"],
            fg=colors["text"],
            font=("Segoe UI", 10, "bold"),
            width=7,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        scale = tk.Scale(
            frame,
            from_=0,
            to=state["duration"],
            resolution=0.05,
            showvalue=False,
            orient="horizontal",
            variable=state[f"{kind}_var"],
            command=lambda value, editor_state=state, range_kind=kind: self.update_clip_editor_selection(
                editor_state,
                range_kind,
                value,
            ),
            bg=colors["panel"],
            fg=colors["text"],
            troughcolor=colors["panel_3"],
            activebackground=colors["accent_hover"],
            highlightthickness=0,
            bd=0,
            sliderrelief="flat",
            sliderlength=18,
            width=10,
        )
        scale.grid(row=0, column=1, sticky="ew", padx=(8, 10))
        state[f"{kind}_scale"] = scale
        tk.Label(
            frame,
            textvariable=state[f"{kind}_label_var"],
            bg=colors["panel"],
            fg=colors["accent"],
            font=("Consolas", 10, "bold"),
            width=12,
            anchor="e",
        ).grid(row=0, column=2, sticky="e", padx=(0, 8))
        self.small_action_button(
            frame,
            "-1s",
            lambda editor_state=state, range_kind=kind: self.step_clip_editor_range(
                editor_state,
                range_kind,
                -1.0,
            ),
        ).grid(row=0, column=3, padx=3)
        self.small_action_button(
            frame,
            "+1s",
            lambda editor_state=state, range_kind=kind: self.step_clip_editor_range(
                editor_state,
                range_kind,
                1.0,
            ),
        ).grid(row=0, column=4, padx=(3, 0))

    def step_clip_editor_range(self, state, kind, delta):
        variable = state[f"{kind}_var"]
        self.update_clip_editor_selection(state, kind, variable.get() + float(delta))

    def update_clip_editor_selection(self, state, changed_kind, value):
        if state.get("updating") or not state["window"].winfo_exists():
            return
        state["updating"] = True
        try:
            start = state["start_var"].get()
            end = state["end_var"].get()
            try:
                changed_value = float(value)
            except (TypeError, ValueError):
                changed_value = start if changed_kind == "start" else end
            if changed_kind == "start":
                start = changed_value
            else:
                end = changed_value
            start, end = clamp_trim_range(start, end, state["duration"])
            state["start_var"].set(start)
            state["end_var"].set(end)
            state["start_label_var"].set(format_precise_duration(start))
            state["end_label_var"].set(format_precise_duration(end))
            state["selection_label_var"].set(
                f"Selected  {format_precise_duration(end - start)}"
            )
        finally:
            state["updating"] = False
        self.schedule_clip_editor_preview(state, changed_kind)

    def schedule_clip_editor_preview(self, state, kind):
        window = state["window"]
        previous = state["preview_after"].get(kind)
        if previous:
            try:
                window.after_cancel(previous)
            except tk.TclError:
                pass
        state["preview_after"][kind] = window.after(
            180,
            lambda: self.start_clip_editor_preview(state, kind),
        )

    def start_clip_editor_preview(self, state, kind):
        window = state["window"]
        if not window.winfo_exists():
            return
        state["preview_after"][kind] = None
        timestamp = state[f"{kind}_var"].get()
        if kind == "end":
            timestamp = max(0.0, min(timestamp - 0.05, state["duration"] - 0.05))
        state["preview_requests"][kind] += 1
        request_id = state["preview_requests"][kind]
        signature = self.thumbnail_signature_for_clip(state["path"], 420, 236)
        digest_value = "|".join(
            str(part) for part in (*signature, kind, round(timestamp, 2))
        )
        digest = hashlib.sha1(digest_value.encode("utf-8", errors="ignore")).hexdigest()
        thumbnail_path = self.last_clip_thumbnail_dir() / f"edit_{digest}.png"
        canvas = state[f"{kind}_canvas"]
        canvas.delete("all")
        canvas.create_text(
            max(1, canvas.winfo_width()) // 2,
            max(1, canvas.winfo_height()) // 2,
            text="Generating preview...",
            fill=self.ui_colors["muted"],
            font=("Segoe UI", 10),
        )

        def worker():
            error = None
            try:
                if not thumbnail_path.exists():
                    self.create_video_thumbnail(
                        state["path"],
                        thumbnail_path,
                        420,
                        236,
                        seek_seconds=timestamp,
                    )
            except Exception as exc:
                error = str(exc)
            try:
                self.root.after(
                    0,
                    lambda: self.finish_clip_editor_preview(
                        state,
                        kind,
                        request_id,
                        thumbnail_path,
                        timestamp,
                        error,
                    ),
                )
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"ShadowClipEditorPreview-{kind}",
        ).start()

    def finish_clip_editor_preview(
        self,
        state,
        kind,
        request_id,
        thumbnail_path,
        timestamp,
        error=None,
    ):
        window = state["window"]
        if not window.winfo_exists() or state["preview_requests"][kind] != request_id:
            return
        if error or not Path(thumbnail_path).exists():
            canvas = state[f"{kind}_canvas"]
            canvas.delete("all")
            canvas.create_text(
                max(1, canvas.winfo_width()) // 2,
                max(1, canvas.winfo_height()) // 2,
                text="Preview unavailable",
                fill=self.ui_colors["muted"],
                font=("Segoe UI", 10),
            )
            return
        try:
            state["preview_images"][kind] = tk.PhotoImage(file=str(thumbnail_path))
            state[f"{kind}_preview_time"] = timestamp
            self.redraw_clip_editor_preview(state, kind)
        except tk.TclError:
            pass

    def redraw_clip_editor_preview(self, state, kind):
        canvas = state.get(f"{kind}_canvas")
        image = state["preview_images"].get(kind)
        if not canvas or image is None:
            return
        try:
            width = max(1, canvas.winfo_width())
            height = max(1, canvas.winfo_height())
            canvas.delete("all")
            canvas.create_image(width // 2, height // 2, image=image)
            canvas.create_rectangle(
                0,
                height - 34,
                width,
                height,
                fill="#090d13",
                outline="",
                stipple="gray50",
            )
            canvas.create_text(
                12,
                height - 17,
                text=format_precise_duration(
                    state.get(f"{kind}_preview_time", 0.0)
                ),
                fill=self.ui_colors["text"],
                font=("Consolas", 10, "bold"),
                anchor="w",
            )
        except tk.TclError:
            pass

    def start_clip_editor_export(self, state):
        if state.get("exporting"):
            return
        path = state["path"]
        start, end = clamp_trim_range(
            state["start_var"].get(),
            state["end_var"].get(),
            state["duration"],
        )
        replace_original = bool(state["replace_var"].get())
        if replace_original and not messagebox.askyesno(
            APP_NAME,
            "Replace the original clip with the trimmed version?\n\n"
            "This cannot be undone.",
            parent=state["window"],
        ):
            return
        output_path = path if replace_original else trimmed_copy_path(path)
        state["exporting"] = True
        state["cancel_event"].clear()
        state["progress_var"].set(0.0)
        state["status_var"].set(
            "Exporting frame-accurate clip..."
            if state["mode_var"].get() == "accurate"
            else "Saving without re-encoding..."
        )
        state["save_button"].configure(state="disabled")
        state["cancel_button"].configure(text="Cancel export")

        def progress_callback(value):
            try:
                self.root.after(
                    0,
                    lambda amount=value: self.update_clip_editor_progress(
                        state,
                        amount,
                    ),
                )
            except (tk.TclError, RuntimeError):
                pass

        def worker():
            result_path = None
            error = None
            try:
                result_path = self.manager.trim_media(
                    path,
                    start,
                    end,
                    output_path=output_path,
                    accurate=state["mode_var"].get() == "accurate",
                    progress_callback=progress_callback,
                    cancel_event=state["cancel_event"],
                )
            except Exception as exc:
                error = str(exc)
            try:
                self.root.after(
                    0,
                    lambda: self.finish_clip_editor_export(
                        state,
                        result_path,
                        error,
                    ),
                )
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(
            target=worker,
            daemon=True,
            name="ShadowClipEditorExport",
        ).start()

    def update_clip_editor_progress(self, state, value):
        if not state["window"].winfo_exists():
            return
        state["progress_var"].set(max(0.0, min(100.0, float(value) * 100.0)))

    def finish_clip_editor_export(self, state, result_path, error=None):
        window = state["window"]
        if not window.winfo_exists():
            return
        state["exporting"] = False
        state["save_button"].configure(state="normal")
        state["cancel_button"].configure(text="Close")
        if error:
            if "cancelled" in error.casefold():
                state["status_var"].set("Export cancelled")
            else:
                state["status_var"].set("Export failed")
                messagebox.showerror(APP_NAME, error, parent=window)
            return
        state["progress_var"].set(100.0)
        state["status_var"].set(f"Saved  {Path(result_path).name}")
        self.refresh_clip_library(force=True)
        self.refresh_status_panel()
        messagebox.showinfo(
            APP_NAME,
            f"Trimmed clip saved.\n\n{result_path}",
            parent=window,
        )

    def close_clip_editor(self, state):
        window = state["window"]
        if state.get("exporting"):
            state["cancel_event"].set()
            state["status_var"].set("Cancelling export...")
            return
        try:
            window.destroy()
        except tk.TclError:
            pass

    def rename_clip_library_path(self, path):
        path = Path(path)
        if not path.exists():
            self.threadsafe_log(f"Media file no longer exists: {path}")
            self.refresh_clip_library(force=True)
            return
        new_name = simpledialog.askstring("Rename media", "New file name:", initialvalue=path.stem, parent=self.root)
        if new_name is None:
            return
        new_name = re.sub(r'[<>:"/\\|?*]', "_", new_name).strip().rstrip(". ")
        if not new_name:
            messagebox.showwarning(APP_NAME, "Please enter a valid file name.", parent=self.root)
            return
        target = path.with_name(f"{new_name}{path.suffix}")
        if target == path:
            return
        if target.exists():
            messagebox.showwarning(APP_NAME, "A file with that name already exists.", parent=self.root)
            return
        self.rename_clip_library_path_when_ready(path, target)

    def clip_gallery_path_is_pending(self, path):
        try:
            resolved = str(Path(path).resolve())
        except OSError:
            resolved = str(Path(path))
        return any(str(signature[0]).casefold() == resolved.casefold() for signature in self.clip_gallery_thumbnail_pending)

    def rename_clip_library_path_when_ready(self, path, target, attempt=0):
        path = Path(path)
        target = Path(target)
        if self.clip_gallery_path_is_pending(path) and attempt < 80:
            self.root.after(100, lambda: self.rename_clip_library_path_when_ready(path, target, attempt + 1))
            return
        try:
            path.rename(target)
            if self.manager.last_clip_path and Path(self.manager.last_clip_path) == path:
                self.manager.last_clip_path = target
            self.threadsafe_log(f"Media renamed: {target}")
            self.refresh_clip_library(force=True)
            self.refresh_status_panel()
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not rename the file.\n\n{exc}", parent=self.root)

    def delete_clip_library_path(self, path):
        path = Path(path)
        if not path.exists():
            self.refresh_clip_library(force=True)
            return
        if not messagebox.askyesno(APP_NAME, f"Move this media file to the Windows Recycle Bin?\n\n{path.name}", icon="question", parent=self.root):
            return
        self.delete_clip_library_path_when_ready(path)

    def delete_clip_library_path_when_ready(self, path, attempt=0):
        path = Path(path)
        if self.clip_gallery_path_is_pending(path) and attempt < 80:
            self.root.after(100, lambda: self.delete_clip_library_path_when_ready(path, attempt + 1))
            return
        try:
            move_path_to_recycle_bin(path, owner_hwnd=self.root.winfo_id())
            if self.manager.last_clip_path and Path(self.manager.last_clip_path) == path:
                self.manager.last_clip_path = None
            self.threadsafe_log(f"Media moved to Recycle Bin: {path}")
            self.refresh_clip_library(force=True)
            self.refresh_status_panel()
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not move the file to the Recycle Bin.\n\n{exc}", parent=self.root)

    def build_capture_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.build_settings_page_header(parent, "Capture", "Choose what ShadowClip captures and which capture engine it uses")
        content = self.create_scrollable_settings_content(parent)
        content.columnconfigure(0, weight=3, uniform="capture")
        content.columnconfigure(1, weight=2, uniform="capture")

        source, body = self.create_settings_panel(content, "Capture source", "Select the desktop, a specific monitor, or one application window.", "capture")
        source.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        body.columnconfigure(0, weight=1)
        ttk.Radiobutton(body, text="All screens", variable=self.vars["capture_mode"], value="desktop_all", style="Modern.TRadiobutton").grid(row=0, column=0, sticky="w", pady=(3, 0))
        tk.Label(body, text="Capture the complete Windows desktop area.", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 8), anchor="w").grid(row=1, column=0, sticky="ew", padx=(23, 0), pady=(2, 10))
        ttk.Radiobutton(body, text="One monitor", variable=self.vars["capture_mode"], value="monitor", style="Modern.TRadiobutton").grid(row=2, column=0, sticky="w")
        self.monitor_combo = ttk.Combobox(body, state="readonly", style="Modern.TCombobox")
        self.monitor_combo.grid(row=3, column=0, sticky="ew", padx=(23, 0), pady=(5, 12))
        self.monitor_combo.bind("<<ComboboxSelected>>", self.on_monitor_selected)
        ttk.Radiobutton(body, text="Window or game title", variable=self.vars["capture_mode"], value="window", style="Modern.TRadiobutton").grid(row=4, column=0, sticky="w")
        window_row = tk.Frame(body, bg=colors["panel"])
        window_row.grid(row=5, column=0, sticky="ew", padx=(23, 0), pady=(5, 3))
        window_row.columnconfigure(0, weight=1)
        self.window_combo = ttk.Combobox(window_row, textvariable=self.vars["window_title"], style="Modern.TCombobox")
        self.window_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.small_action_button(window_row, "Refresh", self.refresh_windows, icon_key="replay").grid(row=0, column=1, sticky="e")

        backend, backend_body = self.create_settings_panel(content, "Capture engine", "Auto is recommended. OBS is the most compatible option for fullscreen games.", "encoder")
        backend.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        backend_body.columnconfigure(0, weight=1)
        self.settings_field_label(backend_body, "Backend", "Capture implementation used for replay and recording.", 0)
        ttk.Combobox(backend_body, state="readonly", style="Modern.TCombobox", textvariable=self.vars["capture_backend"], values=["auto", "ddagrab", "gdigrab", "obs"]).grid(row=1, column=0, sticky="ew", pady=(2, 12))
        self.settings_field_label(backend_body, "Minecraft OBS mode", "Specific game is preferred; display mode is the compatibility fallback.", 2)
        ttk.Combobox(backend_body, state="readonly", style="Modern.TCombobox", textvariable=self.vars["obs_minecraft_capture_mode"], values=["specific_game", "display", "any_fullscreen"]).grid(row=3, column=0, sticky="ew", pady=(2, 12))
        self.settings_toggle(
            backend_body,
            "Capture desktop overlays (WGC)",
            "Records Xbox Game Bar, Crosshair X, and other visible desktop-composited overlays. Automatic recovery falls back to Game Capture if WGC is black.",
            self.vars["capture_desktop_overlays"],
            4,
        )
        note = tk.Frame(backend_body, bg=colors["accent_dark"], highlightbackground="#315512", highlightthickness=1)
        note.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        tk.Label(note, text="OBS handles anti-cheat and exclusive fullscreen games most reliably.", bg=colors["accent_dark"], fg=colors["accent"], font=("Segoe UI", 9, "bold"), justify="left", wraplength=330).pack(fill="x", padx=12, pady=11)

    def build_video_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.build_settings_page_header(parent, "Video", "Control frame rate, replay length, quality, encoder, and memory")
        content = self.create_scrollable_settings_content(parent)
        content.columnconfigure(0, weight=1, uniform="video")
        content.columnconfigure(1, weight=1, uniform="video")

        capture, body = self.create_settings_panel(content, "Capture format", "Core timing and file-format settings.", "video")
        capture.grid(row=0, column=0, sticky="nsew", padx=(0, 9), pady=(0, 18))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        self.settings_field_label(body, "Frame rate", "Frames captured each second.", 0, 0)
        ttk.Spinbox(body, from_=15, to=240, increment=15, textvariable=self.vars["framerate"], width=10, style="Modern.TSpinbox").grid(row=0, column=1, sticky="e", padx=(12, 0), pady=5)
        self.settings_field_label(body, "Replay length", "Maximum seconds saved by Save Clip.", 1, 0)
        ttk.Spinbox(body, from_=10, to=600, increment=10, textvariable=self.vars["clip_seconds"], width=10, style="Modern.TSpinbox").grid(row=1, column=1, sticky="e", padx=(12, 0), pady=5)
        self.settings_field_label(body, "Segment length", "Internal segment duration used by FFmpeg.", 2, 0)
        ttk.Spinbox(body, from_=2, to=15, increment=1, textvariable=self.vars["segment_seconds"], width=10, style="Modern.TSpinbox").grid(row=2, column=1, sticky="e", padx=(12, 0), pady=5)
        self.settings_field_label(body, "Quality", "Lower values preserve more detail.", 3, 0)
        ttk.Spinbox(body, from_=15, to=35, increment=1, textvariable=self.vars["quality"], width=10, style="Modern.TSpinbox").grid(row=3, column=1, sticky="e", padx=(12, 0), pady=5)
        self.settings_field_label(body, "Container", "MKV is resilient; MP4 has broad compatibility.", 4, 0)
        ttk.Combobox(body, state="readonly", textvariable=self.vars["container"], values=["mkv", "mp4"], width=10, style="Modern.TCombobox").grid(row=4, column=1, sticky="e", padx=(12, 0), pady=5)

        encoder, encoder_body = self.create_settings_panel(content, "Encoder and bitrate", "Hardware encoding is selected automatically when available.", "encoder")
        encoder.grid(row=0, column=1, sticky="nsew", padx=(9, 0), pady=(0, 18))
        encoder_body.columnconfigure(0, weight=1)
        encoder_body.columnconfigure(1, weight=0)
        self.settings_field_label(encoder_body, "Video encoder", "GPU encoder or CPU fallback.", 0, 0)
        ttk.Combobox(encoder_body, state="readonly", textvariable=self.vars["video_encoder"], values=VIDEO_ENCODER_VALUES, width=15, style="Modern.TCombobox").grid(row=0, column=1, sticky="e", padx=(12, 0), pady=5)
        self.settings_toggle(encoder_body, "Automatic bitrate", "Calculate bitrate from resolution, FPS, and preset.", self.vars["auto_video_bitrate"], 1, 0, 2, command=lambda: self.sync_auto_video_bitrate(force=True))
        self.settings_field_label(encoder_body, "Quality preset", "Balanced, High, or Ultra.", 2, 0)
        self.auto_bitrate_preset_combo = ttk.Combobox(encoder_body, state="readonly", textvariable=self.vars["auto_bitrate_preset"], values=AUTO_BITRATE_PRESETS, width=15, style="Modern.TCombobox")
        self.auto_bitrate_preset_combo.grid(row=2, column=1, sticky="e", padx=(12, 0), pady=5)
        self.settings_field_label(encoder_body, "Bitrate mode", "Manual quality or target bitrate mode.", 3, 0)
        self.bitrate_mode_combo = ttk.Combobox(encoder_body, state="readonly", textvariable=self.vars["bitrate_mode"], values=["quality", "target"], width=15, style="Modern.TCombobox")
        self.bitrate_mode_combo.grid(row=3, column=1, sticky="e", padx=(12, 0), pady=5)
        self.settings_field_label(encoder_body, "Target / maximum", "Mbps used for target bitrate mode.", 4, 0)
        bitrate_row = tk.Frame(encoder_body, bg=colors["panel"])
        bitrate_row.grid(row=4, column=1, sticky="e", padx=(12, 0), pady=5)
        self.video_bitrate_spin = ttk.Spinbox(bitrate_row, from_=1, to=300, increment=1, textvariable=self.vars["video_bitrate_mbps"], width=7, style="Modern.TSpinbox")
        self.video_bitrate_spin.pack(side="left")
        tk.Label(bitrate_row, text="/", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 10)).pack(side="left", padx=5)
        self.max_bitrate_spin = ttk.Spinbox(bitrate_row, from_=1, to=500, increment=1, textvariable=self.vars["max_bitrate_mbps"], width=7, style="Modern.TSpinbox")
        self.max_bitrate_spin.pack(side="left")

        memory, memory_body = self.create_settings_panel(content, "Replay memory", "OBS keeps compressed replay data in RAM until a clip is saved.", "storage")
        memory.grid(row=1, column=0, columnspan=2, sticky="ew")
        memory_body.columnconfigure(0, weight=1)
        memory_body.columnconfigure(1, weight=0)
        self.settings_toggle(memory_body, "Automatic OBS replay RAM", "Scale memory with clip length and the selected bitrate.", self.vars["obs_replay_ram_auto"], 0, 0, command=lambda: self.sync_auto_obs_replay_buffer(force=True))
        self.obs_replay_buffer_spin = ttk.Spinbox(memory_body, from_=64, to=2048, increment=64, textvariable=self.vars["obs_replay_buffer_mb"], width=12, style="Modern.TSpinbox")
        self.obs_replay_buffer_spin.grid(row=0, column=1, sticky="e", padx=(24, 0), pady=6)
        tk.Label(memory_body, text="MB", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w", padx=(7, 0))

    def build_audio_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.build_settings_page_header(parent, "Audio", "Configure microphone, desktop sound, and synchronization")
        content = self.create_scrollable_settings_content(parent)
        content.columnconfigure(0, weight=1, uniform="audio")
        content.columnconfigure(1, weight=1, uniform="audio")

        microphone, mic_body = self.create_settings_panel(content, "Microphone", "Record your selected input device as part of every clip.", "audio")
        microphone.grid(row=0, column=0, sticky="nsew", padx=(0, 9), pady=(0, 18))
        mic_body.columnconfigure(0, weight=1)
        self.settings_toggle(mic_body, "Enable microphone", "Include microphone audio in replays and recordings.", self.vars["mic_enabled"], 0)
        self.settings_field_label(mic_body, "Input device", "WASAPI microphones and DirectShow inputs are supported.", 1)
        self.mic_combo = ttk.Combobox(mic_body, textvariable=self.vars["mic_device"], style="Modern.TCombobox")
        self.mic_combo.grid(row=2, column=0, sticky="ew", pady=(2, 10))
        self.small_action_button(mic_body, "Scan audio devices", self.scan_audio, icon_key="replay").grid(row=3, column=0, sticky="ew", pady=(5, 0))

        desktop, desktop_body = self.create_settings_panel(content, "Desktop audio", "Capture game, browser, voice-chat, and other system playback.", "audio_bars")
        desktop.grid(row=0, column=1, sticky="nsew", padx=(9, 0), pady=(0, 18))
        desktop_body.columnconfigure(0, weight=1)
        self.settings_toggle(desktop_body, "Enable desktop audio", "Record sound played through the selected output.", self.vars["desktop_audio_enabled"], 0)
        self.settings_field_label(desktop_body, "Output device", "Select the same output device used by Windows and your game.", 1)
        self.desktop_audio_combo = ttk.Combobox(desktop_body, textvariable=self.vars["desktop_audio_device"], style="Modern.TCombobox")
        self.desktop_audio_combo.grid(row=2, column=0, sticky="ew", pady=(2, 10))
        self.settings_field_label(desktop_body, "Capture backend", "WASAPI is recommended for Windows desktop audio.", 3)
        ttk.Combobox(desktop_body, state="readonly", textvariable=self.vars["desktop_audio_backend"], values=["wasapi", "dshow"], style="Modern.TCombobox").grid(row=4, column=0, sticky="ew", pady=(2, 0))

        sync, sync_body = self.create_settings_panel(content, "Synchronization", "Negative offsets move audio earlier when video appears ahead of sound.", "timer")
        sync.grid(row=1, column=0, columnspan=2, sticky="ew")
        sync_body.columnconfigure(0, weight=1)
        sync_body.columnconfigure(1, weight=0)
        self.settings_field_label(sync_body, "Replay clip offset", "Audio timing correction used for saved replay clips.", 0, 0)
        ttk.Spinbox(sync_body, from_=-20000, to=20000, increment=50, textvariable=self.vars["audio_offset_ms"], width=12, style="Modern.TSpinbox").grid(row=0, column=1, sticky="e", padx=(20, 6), pady=5)
        tk.Label(sync_body, text="ms", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w")
        self.settings_field_label(sync_body, "Normal recording offset", "Audio timing correction used for full recordings.", 1, 0)
        ttk.Spinbox(sync_body, from_=-20000, to=20000, increment=50, textvariable=self.vars["recording_audio_offset_ms"], width=12, style="Modern.TSpinbox").grid(row=1, column=1, sticky="e", padx=(20, 6), pady=5)
        tk.Label(sync_body, text="ms", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9)).grid(row=1, column=2, sticky="w")

    def build_hud_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.build_settings_page_header(parent, "HUD", "Control the in-game interface, recording indicator, and notifications")
        content = self.create_scrollable_settings_content(parent)
        content.columnconfigure(0, weight=1, uniform="hud")
        content.columnconfigure(1, weight=1, uniform="hud")

        behavior, behavior_body = self.create_settings_panel(content, "Overlay behavior", "How the Alt+Z interface behaves around games and clips.", "hud")
        behavior.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        behavior_body.columnconfigure(0, weight=1)
        self.settings_toggle(behavior_body, "Fullscreen-safe HUD", "Use the non-activating overlay mode for fullscreen applications.", self.vars["fullscreen_safe_hud"], 0)
        self.settings_toggle(behavior_body, "Close HUD after saving", "Return to the game automatically after Save Clip.", self.vars["hide_overlay_after_clip"], 1)
        self.settings_toggle(behavior_body, "Capture status icons", "Show compact Replay and REC icons while capture is active.", self.vars["recording_indicator_enabled"], 2)
        self.settings_field_label(behavior_body, "HUD gallery size", "Number of recent clips shown inside the Alt+Z gallery.", 3)
        ttk.Spinbox(behavior_body, from_=3, to=50, increment=1, textvariable=self.vars["gallery_limit"], width=12, style="Modern.TSpinbox").grid(row=4, column=0, sticky="w", pady=(2, 0))

        feedback, feedback_body = self.create_settings_panel(content, "Notifications and feedback", "Customize clip-saved and recording status messages.", "audio_bars")
        feedback.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        feedback_body.columnconfigure(0, weight=1)
        feedback_body.columnconfigure(1, weight=0)
        self.settings_toggle(feedback_body, "Event sounds", "Play a short sound for successful capture actions.", self.vars["event_sounds_enabled"], 0, 0, 2)
        self.settings_field_label(feedback_body, "Toast duration", "How long a notification remains visible.", 1, 0)
        ttk.Spinbox(feedback_body, from_=500, to=10000, increment=250, textvariable=self.vars["toast_duration_ms"], width=12, style="Modern.TSpinbox").grid(row=1, column=1, sticky="e", padx=(18, 0), pady=5)
        self.settings_field_label(feedback_body, "Toast position", "Screen corner used for event notifications.", 2, 0)
        ttk.Combobox(feedback_body, state="readonly", textvariable=self.vars["toast_position"], values=["top_right", "bottom_right", "top_left", "bottom_left"], width=16, style="Modern.TCombobox").grid(row=2, column=1, sticky="e", padx=(18, 0), pady=5)
        self.small_action_button(feedback_body, "Show test notification", lambda: self.show_event_toast("ShadowClip", "Notifications are ready.", "clip"), icon_key="check").grid(row=3, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        self.small_action_button(feedback_body, "Preview Pulse Deep sounds", self.preview_event_sound_set, icon_key="audio_bars").grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def build_hotkeys_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.build_settings_page_header(parent, "Settings", "Customize global hotkeys used while ShadowClip is in the background")
        content = self.create_scrollable_settings_content(parent)
        content.columnconfigure(0, weight=1)
        hotkeys, body = self.create_settings_panel(content, "Keyboard shortcuts", "Click a field, then press a standalone key or any key combination.", "settings")
        hotkeys.grid(row=0, column=0, sticky="ew")
        body.columnconfigure(1, weight=1)
        for row, (action, label) in enumerate(HOTKEY_ACTIONS):
            description = {
                "toggle_overlay": "Open or close the in-game HUD.",
                "save_clip": "Save the current replay buffer.",
                "toggle_replay": "Start or stop instant replay.",
                "toggle_recording": "Start or stop a normal recording.",
                "make_borderless": "Convert the foreground game to borderless mode.",
            }.get(action, "Global ShadowClip shortcut.")
            self.settings_field_label(body, label, description, row, 0)
            entry = ttk.Entry(body, textvariable=self.hotkey_vars[action], width=24, style="Modern.TEntry")
            entry.grid(row=row, column=1, sticky="e", padx=(24, 0), pady=5)
            entry.bind("<KeyPress>", lambda event, hotkey_action=action: self.capture_hotkey(event, hotkey_action))
        note = tk.Frame(body, bg=colors["accent_dark"], highlightbackground="#315512", highlightthickness=1)
        note.grid(row=len(HOTKEY_ACTIONS), column=0, columnspan=2, sticky="ew", pady=(16, 6))
        tk.Label(note, text="Standalone keys such as F9, PrintScreen, Home, Numpad1, or X are supported.", bg=colors["accent_dark"], fg=colors["accent"], anchor="w", justify="left", font=("Segoe UI", 9, "bold")).pack(fill="x", padx=12, pady=11)
        actions = tk.Frame(body, bg=colors["panel"])
        actions.grid(row=len(HOTKEY_ACTIONS) + 1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        self.small_action_button(actions, "Restore default hotkeys", self.reset_hotkeys_to_defaults, icon_key="replay").grid(row=0, column=0, sticky="ew")

    def build_storage_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.build_settings_page_header(parent, "Storage", "Manage output paths, startup behavior, library limits, and game profiles")
        content = self.create_scrollable_settings_content(parent)
        content.columnconfigure(0, weight=1, uniform="storage")
        content.columnconfigure(1, weight=1, uniform="storage")

        paths, body = self.create_settings_panel(content, "Paths and runtimes", "Leave FFmpeg and OBS empty to use the bundled versions.", "folder")
        paths.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        body.columnconfigure(1, weight=1)
        self.settings_field_label(body, "Output folder", "Root folder for game/app clip directories.", 0, 0)
        ttk.Entry(body, textvariable=self.vars["output_dir"], style="Modern.TEntry").grid(row=0, column=1, sticky="ew", padx=(18, 8), pady=5)
        self.small_action_button(body, "Browse", self.browse_output, icon_key="folder").grid(row=0, column=2, sticky="e", pady=5)
        self.settings_field_label(body, "FFmpeg path", "Optional custom ffmpeg.exe location.", 1, 0)
        ttk.Entry(body, textvariable=self.vars["ffmpeg_path"], style="Modern.TEntry").grid(row=1, column=1, sticky="ew", padx=(18, 8), pady=5)
        self.small_action_button(body, "Browse", self.browse_ffmpeg, icon_key="folder").grid(row=1, column=2, sticky="e", pady=5)
        self.settings_field_label(body, "OBS path", "Optional custom obs64.exe location.", 2, 0)
        ttk.Entry(body, textvariable=self.vars["obs_path"], style="Modern.TEntry").grid(row=2, column=1, sticky="ew", padx=(18, 8), pady=5)
        self.small_action_button(body, "Browse", self.browse_obs, icon_key="folder").grid(row=2, column=2, sticky="e", pady=5)

        startup, startup_body = self.create_settings_panel(content, "Startup", "Choose what ShadowClip does when Windows or the app starts.", "updates")
        startup.grid(row=1, column=0, sticky="nsew", padx=(0, 9), pady=(0, 18))
        startup_body.columnconfigure(0, weight=1)
        self.settings_toggle(startup_body, "Start with Windows", "Launch minimized with the current Windows user.", self.vars["start_with_windows"], 0)
        self.settings_toggle(startup_body, "Start replay on launch", "Begin buffering automatically after ShadowClip starts.", self.vars["auto_start_replay"], 1)
        self.settings_toggle(startup_body, "Check updates on launch", "Look for a newer GitHub release in the background.", self.vars["check_updates_on_start"], 2)

        library, library_body = self.create_settings_panel(content, "Clip library", "Organize saved media and limit its total storage use.", "storage")
        library.grid(row=1, column=1, sticky="nsew", padx=(9, 0), pady=(0, 18))
        library_body.columnconfigure(0, weight=1)
        library_body.columnconfigure(1, weight=0)
        self.settings_toggle(library_body, "Organize by game/app", "Store media in a folder matching the captured application.", self.vars["organize_clips_by_game"], 0, 0, 2)
        self.settings_toggle(library_body, "Reset replay window after clip", "The next clip contains only newly elapsed replay time.", self.vars["reset_replay_after_clip"], 1, 0, 2)
        self.settings_field_label(library_body, "Maximum storage", "0 disables automatic cleanup of the oldest media.", 2, 0)
        ttk.Spinbox(library_body, from_=0, to=5000, increment=5, textvariable=self.vars["max_storage_gb"], width=12, style="Modern.TSpinbox").grid(row=2, column=1, sticky="e", padx=(18, 6), pady=5)
        tk.Label(library_body, text="GB", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9)).grid(row=2, column=2, sticky="w")

        profiles, profiles_body = self.create_settings_panel(content, "Per-game profiles", "Save the current capture and video settings for the focused game.", "settings")
        profiles.grid(row=2, column=0, columnspan=2, sticky="ew")
        profiles_body.columnconfigure(0, weight=1)
        profiles_body.columnconfigure(1, weight=1)
        self.settings_toggle(profiles_body, "Use per-game profiles", "Apply matching settings automatically before capture actions.", self.vars["use_game_profiles"], 0, 0, 2)
        self.small_action_button(profiles_body, "Save current game profile", self.save_game_profile_for_current_game, icon_key="check").grid(row=1, column=0, sticky="ew", padx=(0, 7), pady=(12, 0))
        self.small_action_button(profiles_body, "Delete current profile", self.delete_game_profile_for_current_game, icon_key="trash").grid(row=1, column=1, sticky="ew", padx=(7, 0), pady=(12, 0))

    def setup_wizard_monitor_labels(self):
        monitors = self.setup_wizard_scan_result.get("monitors") or self.monitors or []
        return [monitor_label(monitor) for monitor in monitors]

    def setup_wizard_selected_monitor_index(self):
        labels = self.setup_wizard_monitor_labels()
        selected = str(self.setup_wizard_vars["monitor"].get() or "")
        try:
            return labels.index(selected)
        except ValueError:
            return 0

    def setup_wizard_recommendations(self):
        monitors = self.setup_wizard_scan_result.get("monitors") or self.monitors or []
        index = self.setup_wizard_selected_monitor_index()
        if monitors:
            index = max(0, min(index, len(monitors) - 1))
            width = int(monitors[index].get("width") or 1920)
            height = int(monitors[index].get("height") or 1080)
        else:
            width, height = 1920, 1080
        try:
            fps = int(self.setup_wizard_vars["framerate"].get())
        except (TypeError, ValueError, tk.TclError):
            fps = 60
        try:
            seconds = int(self.setup_wizard_vars["clip_seconds"].get())
        except (TypeError, ValueError, tk.TclError):
            seconds = 30
        preset = normalize_auto_bitrate_preset(self.setup_wizard_vars["quality_preset"].get())
        bitrate = recommended_video_bitrate_mbps(fps, width, height, preset)
        maximum = recommended_max_bitrate_mbps(bitrate, preset)
        replay_ram = recommended_obs_replay_buffer_mb(seconds, bitrate)
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "seconds": seconds,
            "preset": preset,
            "bitrate": bitrate,
            "maximum": maximum,
            "replay_ram": replay_ram,
        }

    def center_setup_wizard(self):
        wizard = self.setup_wizard
        if not wizard or not wizard.winfo_exists():
            return
        wizard.update_idletasks()
        width = max(900, wizard.winfo_reqwidth())
        height = max(650, wizard.winfo_reqheight())
        screen_width = wizard.winfo_screenwidth()
        screen_height = wizard.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        wizard.geometry(f"{width}x{height}+{x}+{y}")

    def show_setup_wizard(self, auto=False):
        if self.setup_wizard and self.setup_wizard.winfo_exists():
            self.setup_wizard.deiconify()
            self.setup_wizard.lift()
            self.setup_wizard.focus_force()
            return

        colors = self.ui_colors
        self.setup_wizard_auto = bool(auto)
        self.setup_wizard_step = 0
        current_monitor = 0
        try:
            current_monitor = int(self.vars["monitor_index"].get())
        except (TypeError, ValueError, tk.TclError):
            pass
        labels = [monitor_label(monitor) for monitor in (self.monitors or [])]
        if labels:
            current_monitor = max(0, min(current_monitor, len(labels) - 1))
            monitor_value = labels[current_monitor]
        else:
            monitor_value = "Detecting monitors..."
        self.setup_wizard_vars = {
            "monitor": tk.StringVar(value=monitor_value),
            "mic_enabled": tk.BooleanVar(value=bool(self.vars["mic_enabled"].get())),
            "mic_device": tk.StringVar(value=str(self.vars["mic_device"].get() or "")),
            "desktop_audio_enabled": tk.BooleanVar(value=bool(self.vars["desktop_audio_enabled"].get())),
            "desktop_audio_device": tk.StringVar(value=str(self.vars["desktop_audio_device"].get() or "")),
            "framerate": tk.StringVar(value=str(self.vars["framerate"].get() or 60)),
            "clip_seconds": tk.StringVar(value=str(self.vars["clip_seconds"].get() or 30)),
            "quality_preset": tk.StringVar(value=normalize_auto_bitrate_preset(self.vars["auto_bitrate_preset"].get())),
            "start_with_windows": tk.BooleanVar(value=bool(self.vars["start_with_windows"].get())),
            "auto_start_replay": tk.BooleanVar(value=bool(self.vars["auto_start_replay"].get())),
        }

        wizard = tk.Toplevel(self.root)
        self.setup_wizard = wizard
        wizard.title(f"{APP_NAME} Setup")
        wizard.configure(bg=colors["bg"])
        wizard.minsize(900, 650)
        wizard.transient(self.root)
        wizard.protocol("WM_DELETE_WINDOW", self.close_setup_wizard)
        try:
            icon_path = resource_path(APP_ICON_NAME)
            if icon_path.exists():
                wizard.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass

        shell = tk.Frame(wizard, bg=colors["bg"])
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)

        progress = tk.Frame(shell, bg=colors["sidebar"], width=225, highlightbackground=colors["border_soft"], highlightthickness=1)
        progress.grid(row=0, column=0, sticky="ns")
        progress.grid_propagate(False)
        tk.Label(progress, text="ShadowClip", bg=colors["sidebar"], fg=colors["text"], font=("Segoe UI", 18, "bold"), anchor="w").pack(fill="x", padx=24, pady=(28, 5))
        tk.Label(progress, text="First-time setup", bg=colors["sidebar"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w").pack(fill="x", padx=24, pady=(0, 28))
        self.setup_wizard_step_labels = []
        for number, title in enumerate(("System check", "Capture", "Audio", "Video", "Ready"), start=1):
            row = tk.Frame(progress, bg=colors["sidebar"])
            row.pack(fill="x", padx=18, pady=4)
            badge = tk.Label(row, text=str(number), width=3, bg=colors["panel_2"], fg=colors["muted"], font=("Segoe UI", 10, "bold"))
            badge.pack(side="left", padx=(0, 10), ipady=5)
            label = tk.Label(row, text=title, bg=colors["sidebar"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w")
            label.pack(side="left", fill="x", expand=True)
            self.setup_wizard_step_labels.append((row, badge, label))

        content = tk.Frame(shell, bg=colors["bg"])
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.setup_wizard_body = tk.Frame(content, bg=colors["bg"])
        self.setup_wizard_body.grid(row=0, column=0, sticky="nsew", padx=36, pady=(30, 16))

        footer = tk.Frame(content, bg=colors["bg_soft"], height=72, highlightbackground=colors["border_soft"], highlightthickness=1)
        footer.grid(row=1, column=0, sticky="ew")
        footer.grid_propagate(False)
        footer.columnconfigure(0, weight=1)
        self.setup_wizard_back_button = self.small_action_button(footer, "Back", self.setup_wizard_back, icon_key="replay")
        self.setup_wizard_back_button.grid(row=0, column=1, padx=(12, 8), pady=17)
        self.setup_wizard_next_button = self.small_action_button(footer, "Continue", self.setup_wizard_next, accent=True, icon_key="check")
        self.setup_wizard_next_button.grid(row=0, column=2, padx=(0, 22), pady=17)

        self.render_setup_wizard_step()
        self.root.after_idle(self.center_setup_wizard)
        try:
            wizard.grab_set()
            wizard.focus_force()
        except tk.TclError:
            pass
        self.start_setup_wizard_scan()

    def close_setup_wizard(self):
        wizard = self.setup_wizard
        self.setup_wizard = None
        if wizard and wizard.winfo_exists():
            try:
                wizard.grab_release()
            except tk.TclError:
                pass
            wizard.destroy()

    def setup_wizard_heading(self, parent, title, detail):
        colors = self.ui_colors
        tk.Label(parent, text=title, bg=colors["bg"], fg=colors["text"], font=("Segoe UI", 22, "bold"), anchor="w").pack(fill="x")
        tk.Label(parent, text=detail, bg=colors["bg"], fg=colors["muted"], font=("Segoe UI", 11), anchor="w", justify="left", wraplength=600).pack(fill="x", pady=(4, 22))

    def setup_wizard_status_row(self, parent, title, detail, level="pending"):
        colors = self.ui_colors
        palette = {
            "ok": (colors["accent"], "Ready"),
            "warn": ("#f5b942", "Check"),
            "error": ("#ff6b6b", "Missing"),
            "pending": (colors["muted"], "Scanning"),
        }
        color, status = palette.get(level, palette["pending"])
        row = self.dashboard_panel(parent)
        row.pack(fill="x", pady=5)
        row.columnconfigure(1, weight=1)
        tk.Label(row, text="●", bg=colors["panel"], fg=color, font=("Segoe UI", 14)).grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=13)
        tk.Label(row, text=title, bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 10, "bold"), anchor="w").grid(row=0, column=1, sticky="ew", pady=(12, 0))
        tk.Label(row, text=detail, bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=430).grid(row=1, column=1, sticky="ew", pady=(2, 12))
        tk.Label(row, text=status, bg=colors["panel"], fg=color, font=("Segoe UI", 9, "bold"), anchor="e").grid(row=0, column=2, rowspan=2, sticky="e", padx=16)

    def render_setup_wizard_step(self):
        body = getattr(self, "setup_wizard_body", None)
        if not body or not body.winfo_exists():
            return
        colors = self.ui_colors
        for child in body.winfo_children():
            child.destroy()
        step = max(0, min(4, int(self.setup_wizard_step)))
        self.setup_wizard_step = step
        for index, (row, badge, label) in enumerate(self.setup_wizard_step_labels):
            active = index == step
            complete = index < step
            row.configure(bg=colors["sidebar"])
            badge.configure(
                text="✓" if complete else str(index + 1),
                bg=colors["accent"] if (active or complete) else colors["panel_2"],
                fg="#071007" if (active or complete) else colors["muted"],
            )
            label.configure(fg=colors["text"] if active else (colors["accent"] if complete else colors["muted"]))
        self.setup_wizard_back_button.configure(state="normal" if step > 0 else "disabled")
        self.setup_wizard_next_button.configure(text="Finish setup" if step == 4 else "Continue")
        if step == 0 and self.setup_wizard_scan_running:
            self.setup_wizard_next_button.configure(state="disabled")
        else:
            self.setup_wizard_next_button.configure(state="normal")

        if step == 0:
            self.render_setup_wizard_system_step(body)
        elif step == 1:
            self.render_setup_wizard_capture_step(body)
        elif step == 2:
            self.render_setup_wizard_audio_step(body)
        elif step == 3:
            self.render_setup_wizard_video_step(body)
        else:
            self.render_setup_wizard_ready_step(body)

    def render_setup_wizard_system_step(self, body):
        self.setup_wizard_heading(body, "Let's prepare ShadowClip", "ShadowClip checks the bundled capture tools, your graphics hardware, monitors, audio devices, and output folder.")
        result = self.setup_wizard_scan_result
        if not result:
            for title in ("OBS capture runtime", "FFmpeg media tools", "Hardware encoder", "Monitors and audio"):
                self.setup_wizard_status_row(body, title, "Detection is in progress...", "pending")
            return
        self.setup_wizard_status_row(body, "OBS capture runtime", result.get("obs_detail", "Not detected"), "ok" if result.get("obs") else "error")
        self.setup_wizard_status_row(body, "FFmpeg media tools", result.get("ffmpeg_detail", "Not detected"), "ok" if result.get("ffmpeg") else "error")
        encoder = str(result.get("encoder_label") or "CPU fallback")
        self.setup_wizard_status_row(body, "Hardware encoder", encoder, "ok" if result.get("hardware_encoder") else "warn")
        device_detail = f"{len(result.get('monitors') or [])} monitor(s), {len(result.get('mics') or [])} microphone(s), {len(result.get('loopbacks') or [])} desktop output(s)"
        self.setup_wizard_status_row(body, "Displays and audio", device_detail, "ok" if result.get("monitors") else "error")
        if not result.get("output_writable"):
            self.setup_wizard_status_row(body, "Output folder", result.get("output_detail", "Not writable"), "error")
        self.small_action_button(body, "Scan again", self.start_setup_wizard_scan, icon_key="replay").pack(anchor="e", pady=(12, 0))

    def render_setup_wizard_capture_step(self, body):
        colors = self.ui_colors
        self.setup_wizard_heading(body, "Choose the capture display", "OBS remains the capture engine for broad fullscreen and anti-cheat compatibility. Select the monitor where you normally play.")
        panel, panel_body = self.create_settings_panel(body, "Primary capture monitor", "ShadowClip can still detect fullscreen games on this display.", "capture")
        panel.pack(fill="x")
        panel_body.columnconfigure(0, weight=1)
        monitor_combo = ttk.Combobox(panel_body, state="readonly", textvariable=self.setup_wizard_vars["monitor"], values=self.setup_wizard_monitor_labels(), style="Modern.TCombobox")
        monitor_combo.grid(row=0, column=0, sticky="ew", pady=(2, 14))
        note = tk.Frame(panel_body, bg=colors["accent_dark"], highlightbackground="#315512", highlightthickness=1)
        note.grid(row=1, column=0, sticky="ew")
        tk.Label(note, text="Recommended: one monitor + OBS. This avoids oversized multi-monitor canvases and keeps resolution changes predictable.", bg=colors["accent_dark"], fg=colors["accent"], font=("Segoe UI", 9, "bold"), justify="left", wraplength=540).pack(fill="x", padx=14, pady=12)

    def render_setup_wizard_audio_step(self, body):
        self.setup_wizard_heading(body, "Configure audio", "Choose whether clips include your microphone and Windows desktop sound. You can change both later.")
        result = self.setup_wizard_scan_result
        mics = result.get("mics") or []
        loopbacks = result.get("loopbacks") or []
        panel, panel_body = self.create_settings_panel(body, "Audio sources", "WASAPI is used for low-overhead Windows audio capture.", "audio")
        panel.pack(fill="x")
        panel_body.columnconfigure(0, weight=1)
        self.settings_toggle(panel_body, "Record microphone", "Include voice input in clips and recordings.", self.setup_wizard_vars["mic_enabled"], 0)
        ttk.Combobox(panel_body, state="readonly" if mics else "disabled", textvariable=self.setup_wizard_vars["mic_device"], values=mics, style="Modern.TCombobox").grid(row=1, column=0, sticky="ew", padx=(23, 0), pady=(0, 14))
        self.settings_toggle(panel_body, "Record desktop audio", "Include game, browser, and voice-chat playback.", self.setup_wizard_vars["desktop_audio_enabled"], 2)
        ttk.Combobox(panel_body, state="readonly" if loopbacks else "disabled", textvariable=self.setup_wizard_vars["desktop_audio_device"], values=loopbacks, style="Modern.TCombobox").grid(row=3, column=0, sticky="ew", padx=(23, 0), pady=(0, 8))

    def update_setup_wizard_recommendation_label(self, _event=None):
        label = getattr(self, "setup_wizard_recommendation_label", None)
        if not label or not label.winfo_exists():
            return
        recommendation = self.setup_wizard_recommendations()
        label.configure(text=(
            f"{recommendation['width']}x{recommendation['height']} at {recommendation['fps']} FPS  |  "
            f"{recommendation['bitrate']}/{recommendation['maximum']} Mbps  |  "
            f"Replay RAM {recommendation['replay_ram']} MB"
        ))

    def render_setup_wizard_video_step(self, body):
        colors = self.ui_colors
        self.setup_wizard_heading(body, "Set clip quality", "Choose only frame rate, clip length, and a quality target. ShadowClip calculates bitrate and replay memory automatically.")
        panel, panel_body = self.create_settings_panel(body, "Recommended video settings", "Hardware encoder selection remains automatic.", "video")
        panel.pack(fill="x")
        panel_body.columnconfigure(0, weight=1)
        panel_body.columnconfigure(1, weight=1)
        self.settings_field_label(panel_body, "Frame rate", "60 FPS is recommended; 120 FPS uses more GPU and storage.", 0, 0)
        fps_combo = ttk.Combobox(panel_body, state="readonly", textvariable=self.setup_wizard_vars["framerate"], values=[30, 60, 120, 144, 240], style="Modern.TCombobox")
        fps_combo.grid(row=1, column=0, sticky="ew", padx=(0, 9), pady=(2, 14))
        self.settings_field_label(panel_body, "Replay length", "How much recent gameplay Save Clip keeps.", 0, 1)
        length_combo = ttk.Combobox(panel_body, state="readonly", textvariable=self.setup_wizard_vars["clip_seconds"], values=[15, 30, 60, 120, 180, 300], style="Modern.TCombobox")
        length_combo.grid(row=1, column=1, sticky="ew", padx=(9, 0), pady=(2, 14))
        self.settings_field_label(panel_body, "Quality preset", "High is the best default balance for gameplay.", 2, 0, 2)
        preset_combo = ttk.Combobox(panel_body, state="readonly", textvariable=self.setup_wizard_vars["quality_preset"], values=AUTO_BITRATE_PRESETS, style="Modern.TCombobox")
        preset_combo.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 16))
        recommendation = tk.Frame(panel_body, bg=colors["accent_dark"], highlightbackground="#315512", highlightthickness=1)
        recommendation.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.setup_wizard_recommendation_label = tk.Label(recommendation, bg=colors["accent_dark"], fg=colors["accent"], font=("Segoe UI", 9, "bold"), justify="left", anchor="w")
        self.setup_wizard_recommendation_label.pack(fill="x", padx=14, pady=12)
        for combo in (fps_combo, length_combo, preset_combo):
            combo.bind("<<ComboboxSelected>>", self.update_setup_wizard_recommendation_label)
        self.update_setup_wizard_recommendation_label()

    def render_setup_wizard_ready_step(self, body):
        colors = self.ui_colors
        self.setup_wizard_heading(body, "ShadowClip is ready", "Review the automatic configuration. Finish setup to save it and make the selected startup behavior active.")
        recommendation = self.setup_wizard_recommendations()
        result = self.setup_wizard_scan_result
        panel, panel_body = self.create_settings_panel(body, "Configuration summary", "All advanced controls remain available in the main settings pages.", "check")
        panel.pack(fill="x")
        summary = [
            ("Capture", self.setup_wizard_vars["monitor"].get() or "Monitor 1"),
            ("Encoder", str(result.get("encoder_label") or "Automatic")),
            ("Video", f"{recommendation['width']}x{recommendation['height']} at {recommendation['fps']} FPS, {recommendation['seconds']}s replay"),
            ("Automatic tuning", f"{recommendation['bitrate']}/{recommendation['maximum']} Mbps, {recommendation['replay_ram']} MB replay RAM"),
            ("Audio", f"Microphone {'on' if self.setup_wizard_vars['mic_enabled'].get() else 'off'}, desktop {'on' if self.setup_wizard_vars['desktop_audio_enabled'].get() else 'off'}"),
            ("Next step", "Run Capture test from the Updates page after setup."),
        ]
        panel_body.columnconfigure(1, weight=1)
        for row, (title, value) in enumerate(summary):
            tk.Label(panel_body, text=title, bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9), anchor="w").grid(row=row, column=0, sticky="w", pady=5, padx=(0, 20))
            tk.Label(panel_body, text=value, bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 9, "bold"), anchor="w", justify="left", wraplength=430).grid(row=row, column=1, sticky="ew", pady=5)
        startup, startup_body = self.create_settings_panel(body, "Startup behavior", "These options can be changed later under Storage.", "updates")
        startup.pack(fill="x", pady=(14, 0))
        startup_body.columnconfigure(0, weight=1)
        self.settings_toggle(startup_body, "Start ShadowClip with Windows", "Launch silently for the current Windows user.", self.setup_wizard_vars["start_with_windows"], 0)
        self.settings_toggle(startup_body, "Start Instant Replay automatically", "Begin buffering as soon as ShadowClip opens.", self.setup_wizard_vars["auto_start_replay"], 1)

    def setup_wizard_back(self):
        if self.setup_wizard_step <= 0:
            return
        self.setup_wizard_step -= 1
        self.render_setup_wizard_step()

    def setup_wizard_next(self):
        if self.setup_wizard_step < 4:
            self.setup_wizard_step += 1
            self.render_setup_wizard_step()
            return
        self.finish_setup_wizard()

    def start_setup_wizard_scan(self):
        if self.setup_wizard_scan_running:
            return
        self.setup_wizard_scan_running = True
        self.setup_wizard_scan_result = {}
        self.render_setup_wizard_step()
        config = self.collect_config().copy()
        thread = threading.Thread(target=self.setup_wizard_scan_worker, args=(config,), daemon=True)
        thread.start()

    def setup_wizard_scan_worker(self, config):
        result = {
            "monitors": [],
            "mics": [],
            "loopbacks": [],
            "obs": "",
            "ffmpeg": "",
            "encoder": "libx264",
            "hardware_encoder": False,
            "output_writable": False,
        }
        manager = FfmpegManager(config, lambda _message: None)
        try:
            result["monitors"] = enum_monitors()
        except Exception as exc:
            result["monitor_error"] = str(exc)
        try:
            obs = manager.find_obs_exe()
            result["obs"] = str(obs or "")
            result["obs_detail"] = str(obs) if obs else "Bundled OBS runtime was not found."
        except Exception as exc:
            result["obs_detail"] = str(exc)
        try:
            ffmpeg = manager.find_ffmpeg()
            result["ffmpeg"] = str(ffmpeg or "")
            result["ffmpeg_detail"] = str(ffmpeg) if ffmpeg else "Bundled FFmpeg was not found."
        except Exception as exc:
            result["ffmpeg_detail"] = str(exc)
        try:
            encoder = manager.resolve_video_encoder(ffmpeg_limited=False, log_selection=False)
            result["encoder"] = encoder
            result["encoder_label"] = video_encoder_label(encoder)
            result["hardware_encoder"] = encoder in HARDWARE_VIDEO_ENCODERS
            result["gpu_names"] = manager.detect_gpu_adapter_names()
        except Exception as exc:
            result["encoder_label"] = f"Detection failed: {exc}"
        try:
            result["mics"] = sorted(set(manager.scan_soundcard_mics()), key=str.casefold)
        except Exception as exc:
            result["mic_error"] = str(exc)
        try:
            result["loopbacks"] = sorted(set(manager.scan_wasapi_loopbacks()), key=str.casefold)
        except Exception as exc:
            result["loopback_error"] = str(exc)
        try:
            output_dir = manager.output_dir()
            output_dir.mkdir(parents=True, exist_ok=True)
            probe = output_dir / f".shadowclip_setup_{uuid.uuid4().hex}.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            result["output_writable"] = True
            result["output_detail"] = str(output_dir)
        except Exception as exc:
            result["output_detail"] = str(exc)
        self.root.after(0, lambda data=result: self.finish_setup_wizard_scan(data))

    def finish_setup_wizard_scan(self, result):
        self.setup_wizard_scan_running = False
        self.setup_wizard_scan_result = result
        self.monitors = result.get("monitors") or self.monitors
        labels = self.setup_wizard_monitor_labels()
        selected = self.setup_wizard_vars.get("monitor")
        if selected is not None and labels and selected.get() not in labels:
            primary = next((monitor for monitor in self.monitors if monitor.get("primary")), self.monitors[0])
            selected.set(monitor_label(primary))
        mics = result.get("mics") or []
        loopbacks = result.get("loopbacks") or []
        mic_var = self.setup_wizard_vars.get("mic_device")
        desktop_var = self.setup_wizard_vars.get("desktop_audio_device")
        if mic_var is not None and mics and mic_var.get() not in mics:
            preferred = next((device for device in mics if "broadcast" in device.casefold()), mics[0])
            mic_var.set(preferred)
        if desktop_var is not None and loopbacks and desktop_var.get() not in loopbacks:
            preferred = loopbacks[0]
            if sc is not None:
                try:
                    default_name = sc.default_speaker().name
                    preferred = next((device for device in loopbacks if device == default_name), preferred)
                except Exception:
                    pass
            desktop_var.set(preferred)
        if self.setup_wizard_auto:
            if mics:
                self.setup_wizard_vars["mic_enabled"].set(True)
            if loopbacks:
                self.setup_wizard_vars["desktop_audio_enabled"].set(True)
        self.threadsafe_log(
            f"Setup scan found {len(result.get('monitors') or [])} monitor(s), "
            f"{len(mics)} microphone(s), {len(loopbacks)} desktop audio output(s), "
            f"and {result.get('encoder_label') or 'no encoder'}."
        )
        self.render_setup_wizard_step()

    def finish_setup_wizard(self):
        recommendation = self.setup_wizard_recommendations()
        monitor_index = self.setup_wizard_selected_monitor_index()
        result = self.setup_wizard_scan_result
        if not result.get("obs") or not result.get("ffmpeg"):
            proceed = messagebox.askyesno(
                APP_NAME,
                "One or more bundled capture components were not detected.\n\nFinish setup anyway?",
                parent=self.setup_wizard,
            )
            if not proceed:
                self.setup_wizard_step = 0
                self.render_setup_wizard_step()
                return

        self.vars["capture_mode"].set("monitor")
        self.vars["capture_backend"].set("obs")
        self.vars["monitor_index"].set(monitor_index)
        self.vars["video_encoder"].set("auto")
        self.vars["framerate"].set(recommendation["fps"])
        self.vars["clip_seconds"].set(recommendation["seconds"])
        self.vars["auto_video_bitrate"].set(True)
        self.vars["auto_bitrate_preset"].set(recommendation["preset"])
        self.vars["obs_replay_ram_auto"].set(True)
        self.vars["mic_enabled"].set(bool(self.setup_wizard_vars["mic_enabled"].get()))
        self.vars["mic_device"].set(self.setup_wizard_vars["mic_device"].get())
        self.vars["desktop_audio_enabled"].set(bool(self.setup_wizard_vars["desktop_audio_enabled"].get()))
        self.vars["desktop_audio_backend"].set("wasapi")
        self.vars["desktop_audio_device"].set(self.setup_wizard_vars["desktop_audio_device"].get())
        self.vars["start_with_windows"].set(bool(self.setup_wizard_vars["start_with_windows"].get()))
        self.vars["auto_start_replay"].set(bool(self.setup_wizard_vars["auto_start_replay"].get()))
        self.sync_auto_video_bitrate(force=True)
        self.sync_auto_obs_replay_buffer(force=True)
        config = self.collect_config()
        config["setup_completed"] = True
        config["setup_version"] = APP_VERSION
        self.config = config
        self.manager.update_config(config)
        save_config(config)
        self.apply_autostart(bool(config.get("start_with_windows", False)))
        self.clear_settings_dirty()
        self.refresh_monitors()
        self.threadsafe_log(f"First-time setup completed with {video_encoder_label(result.get('encoder') or 'auto')} recommendations.")
        auto_start_replay = bool(config.get("auto_start_replay", False))
        check_updates = bool(config.get("check_updates_on_start", True))
        self.close_setup_wizard()
        self.show_main_page("home")
        self.show_event_toast("Setup complete", "ShadowClip is ready to capture.", "check")
        if auto_start_replay and not self.replay_running():
            self.root.after(500, self.auto_start_replay)
        if check_updates:
            self.root.after(1800, lambda: self.check_for_updates(silent=True))

    def capture_self_test_check(self, checks, level, name, detail, suggestion=""):
        checks.append({
            "level": level,
            "name": name,
            "detail": str(detail),
            "suggestion": str(suggestion or ""),
        })

    def capture_self_test_summary(self, checks):
        return {
            "ok": sum(1 for check in checks if check.get("level") == "ok"),
            "warn": sum(1 for check in checks if check.get("level") == "warn"),
            "error": sum(1 for check in checks if check.get("level") == "error"),
        }

    def parse_media_frame_rate(self, value):
        text = str(value or "").strip()
        if not text or text in {"0/0", "N/A"}:
            return 0.0
        try:
            if "/" in text:
                numerator, denominator = text.split("/", 1)
                denominator = float(denominator)
                return float(numerator) / denominator if denominator else 0.0
            return float(text)
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0

    def capture_self_test_expected_context(self, config, test_seconds):
        try:
            width, height = self.video_dimensions_for_config(config)
        except Exception:
            width, height = 0, 0
        return {
            "width": int(width or 0),
            "height": int(height or 0),
            "fps": int(config.get("framerate", DEFAULT_CONFIG["framerate"]) or DEFAULT_CONFIG["framerate"]),
            "seconds": int(test_seconds),
            "audio_expected": bool(config.get("mic_enabled") or config.get("desktop_audio_enabled")),
            "mic_expected": bool(config.get("mic_enabled")),
            "desktop_audio_expected": bool(config.get("desktop_audio_enabled")),
        }

    def analyze_capture_self_test_clip(self, media_path, expected):
        path = Path(media_path)
        checks = []
        result = {
            "path": str(path),
            "checks": checks,
            "expected": expected,
            "metadata": {},
        }
        if not path.exists():
            self.capture_self_test_check(checks, "error", "Saved file", "The test clip does not exist.", "Check the output folder and export a debug report.")
            result["summary"] = self.capture_self_test_summary(checks)
            return result

        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size >= 128 * 1024:
            self.capture_self_test_check(checks, "ok", "Saved file", f"{format_file_size(size)} written to {path.parent}.")
        else:
            self.capture_self_test_check(checks, "error", "Saved file", f"The file is unexpectedly small ({format_file_size(size)}).", "Run Check setup and verify free disk space.")

        ffprobe = self.manager.find_ffprobe()
        if not ffprobe:
            self.capture_self_test_check(checks, "error", "Media inspection", "FFprobe was not found.", "Reinstall ShadowClip so the bundled FFmpeg tools are restored.")
            result["summary"] = self.capture_self_test_summary(checks)
            return result

        try:
            probe = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-show_entries", "format=duration,size,start_time:stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,start_time,duration,channels,sample_rate",
                    "-of", "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=CREATE_NO_WINDOW,
            )
            if probe.returncode != 0:
                raise RuntimeError((probe.stderr or probe.stdout or "FFprobe failed").strip())
            payload = json.loads(probe.stdout or "{}")
        except Exception as exc:
            self.capture_self_test_check(checks, "error", "Media inspection", f"The clip could not be inspected: {exc}", "Open the test clip manually and export a debug report.")
            result["summary"] = self.capture_self_test_summary(checks)
            return result

        streams = payload.get("streams") or []
        video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        video = video_streams[0] if video_streams else {}
        audio = audio_streams[0] if audio_streams else {}
        format_info = payload.get("format") or {}
        try:
            duration = float(format_info.get("duration") or video.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        fps = self.parse_media_frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
        result["metadata"] = {
            "duration": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "video_codec": str(video.get("codec_name") or ""),
            "audio_codec": str(audio.get("codec_name") or ""),
            "audio_streams": len(audio_streams),
            "size": size,
        }

        if video_streams:
            codec = str(video.get("codec_name") or "unknown").upper()
            self.capture_self_test_check(checks, "ok", "Video stream", f"{codec} video stream detected.")
        else:
            self.capture_self_test_check(checks, "error", "Video stream", "No video stream was found.", "Switch Capture backend to OBS and run the test again.")

        target_seconds = float(expected.get("seconds") or 10)
        if duration >= max(4.0, target_seconds * 0.60) and duration <= target_seconds + 4.0:
            self.capture_self_test_check(checks, "ok", "Clip duration", f"{duration:.2f} seconds captured.")
        elif duration > 0:
            self.capture_self_test_check(checks, "warn", "Clip duration", f"Expected about {target_seconds:.0f} seconds, received {duration:.2f} seconds.", "Run the test again after the replay buffer has fully started.")
        else:
            self.capture_self_test_check(checks, "error", "Clip duration", "No valid media duration was reported.", "Open the clip manually and run Check setup.")

        expected_width = int(expected.get("width") or 0)
        expected_height = int(expected.get("height") or 0)
        if width and height and (not expected_width or not expected_height or (width == expected_width and height == expected_height)):
            self.capture_self_test_check(checks, "ok", "Resolution", f"{width}x{height}.")
        elif width and height:
            self.capture_self_test_check(checks, "warn", "Resolution", f"Captured {width}x{height}; selected display is {expected_width}x{expected_height}.", "Check the selected monitor and restart replay after changing display resolution.")
        else:
            self.capture_self_test_check(checks, "error", "Resolution", "No valid video dimensions were reported.", "Switch to OBS display capture and run the test again.")

        expected_fps = float(expected.get("fps") or 0)
        if fps and (not expected_fps or fps >= expected_fps * 0.80):
            self.capture_self_test_check(checks, "ok", "Frame rate", f"Average stream rate: {fps:.2f} FPS.")
        elif fps:
            self.capture_self_test_check(checks, "warn", "Frame rate", f"Average stream rate is {fps:.2f} FPS; configured value is {expected_fps:.0f} FPS.", "Lower FPS or quality, and confirm that a hardware encoder is selected.")
        else:
            self.capture_self_test_check(checks, "warn", "Frame rate", "The average frame rate could not be determined.", "Play the clip manually and inspect motion smoothness.")

        ffmpeg = self.manager.find_ffmpeg()
        if ffmpeg and video_streams and duration > 0:
            try:
                visual = subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner", "-nostats", "-v", "info",
                        "-i", str(path),
                        "-vf", "blackdetect=d=0.5:pix_th=0.10",
                        "-an", "-f", "null", "-",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30,
                    creationflags=CREATE_NO_WINDOW,
                )
                black_durations = [float(value) for value in re.findall(r"black_duration:([0-9.]+)", visual.stderr or "")]
                black_seconds = min(duration, sum(black_durations))
                black_ratio = black_seconds / duration if duration else 0.0
                result["metadata"]["black_ratio"] = black_ratio
                if black_ratio >= 0.90:
                    self.capture_self_test_check(checks, "error", "Visible picture", f"About {black_ratio * 100:.0f}% of the test clip is black.", "Use OBS display capture, update the GPU driver, and disable protected-content playback before testing again.")
                elif black_ratio >= 0.50:
                    self.capture_self_test_check(checks, "warn", "Visible picture", f"About {black_ratio * 100:.0f}% of the test clip is black.", "Keep a bright moving window or game visible during the next test.")
                else:
                    self.capture_self_test_check(checks, "ok", "Visible picture", f"No major black-screen problem detected ({black_ratio * 100:.0f}% black frames).")
            except Exception as exc:
                self.capture_self_test_check(checks, "warn", "Visible picture", f"Black-screen analysis was unavailable: {exc}", "Open the test clip and verify the picture manually.")

        audio_expected = bool(expected.get("audio_expected"))
        if audio_streams:
            codec = str(audio.get("codec_name") or "unknown").upper()
            channels = int(audio.get("channels") or 0)
            detail = f"{len(audio_streams)} audio stream(s), {codec}"
            if channels:
                detail += f", {channels} channel(s)"
            self.capture_self_test_check(checks, "ok", "Audio stream", detail + ".")
        elif audio_expected:
            enabled = []
            if expected.get("mic_expected"):
                enabled.append("microphone")
            if expected.get("desktop_audio_expected"):
                enabled.append("desktop audio")
            self.capture_self_test_check(checks, "error", "Audio stream", f"No audio stream was found although {' and '.join(enabled)} is enabled.", "Scan audio devices again and select the active Windows playback and microphone devices.")
        else:
            self.capture_self_test_check(checks, "ok", "Audio stream", "Audio is disabled in ShadowClip settings, so no stream was expected.")

        if video_streams and audio_streams:
            try:
                video_start = float(video.get("start_time") or format_info.get("start_time") or 0)
                audio_start = float(audio.get("start_time") or format_info.get("start_time") or 0)
                start_delta = audio_start - video_start
                result["metadata"]["audio_video_start_delta"] = start_delta
                if abs(start_delta) <= 0.75:
                    self.capture_self_test_check(checks, "ok", "Audio/video timeline", f"Stream start difference: {start_delta * 1000:+.0f} ms.")
                else:
                    self.capture_self_test_check(checks, "warn", "Audio/video timeline", f"Audio starts {start_delta:+.2f} seconds relative to video.", "Adjust the replay audio offset and confirm sync by watching the test clip.")
            except (TypeError, ValueError):
                self.capture_self_test_check(checks, "warn", "Audio/video timeline", "Stream start timestamps were unavailable.", "Check synchronization manually in the test clip.")

        if ffmpeg and audio_streams and duration > 0:
            try:
                sound = subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner", "-nostats", "-v", "info",
                        "-i", str(path),
                        "-vn", "-af", "silencedetect=n=-50dB:d=1",
                        "-f", "null", "-",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30,
                    creationflags=CREATE_NO_WINDOW,
                )
                silence_durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", sound.stderr or "")]
                silence_seconds = min(duration, sum(silence_durations))
                silence_ratio = silence_seconds / duration if duration else 0.0
                result["metadata"]["silence_ratio"] = silence_ratio
                if silence_ratio >= 0.90 and audio_expected:
                    self.capture_self_test_check(checks, "warn", "Audio activity", f"The audio stream is nearly silent ({silence_ratio * 100:.0f}%).", "Play desktop audio and speak during the next test, then verify the selected devices.")
                else:
                    self.capture_self_test_check(checks, "ok", "Audio activity", f"Audio data is present ({silence_ratio * 100:.0f}% detected silence).")
            except Exception as exc:
                self.capture_self_test_check(checks, "warn", "Audio activity", f"Silence analysis was unavailable: {exc}", "Listen to the saved test clip manually.")

        result["summary"] = self.capture_self_test_summary(checks)
        return result

    def capture_self_test_update(self, status, progress=None):
        def apply():
            if self.capture_self_test_status_label and self.capture_self_test_status_label.winfo_exists():
                self.capture_self_test_status_label.configure(text=status)
            if progress is not None and self.capture_self_test_progress and self.capture_self_test_progress.winfo_exists():
                self.capture_self_test_progress["value"] = max(0, min(100, float(progress)))
        try:
            self.root.after(0, apply)
        except (tk.TclError, RuntimeError):
            pass

    def build_capture_self_test_progress(self):
        colors = self.ui_colors
        window = tk.Toplevel(self.root)
        self.capture_self_test_window = window
        window.title(f"{APP_NAME} Capture Test")
        window.configure(bg=colors["bg"])
        window.resizable(False, False)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", lambda: messagebox.showinfo(APP_NAME, "The capture test is still running.", parent=window))
        panel = self.dashboard_panel(window)
        panel.pack(fill="both", expand=True, padx=22, pady=22)
        header = tk.Frame(panel, bg=colors["panel"])
        header.pack(fill="x", padx=24, pady=(22, 8))
        icon = self.create_icon_canvas(header, "record", size=46, fg=colors["accent"], bg=colors["panel"])
        icon.pack(side="left", padx=(0, 16))
        text = tk.Frame(header, bg=colors["panel"])
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text="Testing capture", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 18, "bold"), anchor="w").pack(fill="x")
        tk.Label(text, text="Keep a moving picture visible, play desktop audio, and speak into the microphone.", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 9), anchor="w", justify="left", wraplength=520).pack(fill="x", pady=(3, 0))
        self.capture_self_test_status_label = tk.Label(panel, text="Preparing replay buffer...", bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 10, "bold"), anchor="w")
        self.capture_self_test_status_label.pack(fill="x", padx=24, pady=(18, 8))
        self.capture_self_test_progress = ttk.Progressbar(panel, orient="horizontal", mode="determinate", maximum=100, value=2)
        self.capture_self_test_progress.pack(fill="x", padx=24, pady=(0, 12), ipady=3)
        tk.Label(panel, text="The active replay history is temporarily reset and restored to its previous running state after the test.", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=570).pack(fill="x", padx=24, pady=(0, 22))
        window.update_idletasks()
        width = 650
        height = 300
        x = max(0, self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2)
        y = max(0, self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.lift()

    def close_capture_self_test_window(self):
        window = self.capture_self_test_window
        self.capture_self_test_window = None
        self.capture_self_test_status_label = None
        self.capture_self_test_progress = None
        if window and window.winfo_exists():
            try:
                window.destroy()
            except tk.TclError:
                pass

    def run_capture_self_test(self):
        if self.capture_self_test_running:
            if self.capture_self_test_window and self.capture_self_test_window.winfo_exists():
                self.capture_self_test_window.lift()
            return
        if self.recording_running():
            messagebox.showwarning(APP_NAME, "Stop the current normal recording before starting the capture test.", parent=self.root)
            return
        if self.manager.save_lock.locked():
            messagebox.showwarning(APP_NAME, "A clip is currently being saved. Wait for it to finish, then run the test.", parent=self.root)
            return
        replay_was_running = self.replay_running()
        if replay_was_running:
            proceed = messagebox.askyesno(
                APP_NAME,
                "The test restarts Instant Replay and clears its current unsaved history.\n\nContinue?",
                parent=self.root,
            )
            if not proceed:
                return
        if self.save_settings() is False:
            return
        self.prepare_capture_action("capture self-test")
        original_config = json.loads(json.dumps(self.config))
        test_seconds = 10
        expected = self.capture_self_test_expected_context(original_config, test_seconds)
        self.capture_self_test_running = True
        self.capture_self_test_last_result = None
        self.build_capture_self_test_progress()
        self.threadsafe_log("Capture self-test started; replay history will be temporarily reset.")
        thread = threading.Thread(
            target=self.capture_self_test_worker,
            args=(original_config, replay_was_running, test_seconds, expected),
            daemon=True,
        )
        thread.start()

    def capture_self_test_clip_path(self, source_path):
        source = Path(source_path)
        test_dir = self.manager.output_dir() / "ShadowClip Tests"
        test_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target = test_dir / f"Replay Test {stamp}{source.suffix.lower()}"
        counter = 2
        while target.exists():
            target = test_dir / f"Replay Test {stamp} ({counter}){source.suffix.lower()}"
            counter += 1
        source.replace(target)
        self.manager.last_clip_path = target
        return target

    def capture_self_test_worker(self, original_config, replay_was_running, test_seconds, expected):
        test_started_replay = False
        clip_path = None
        capture_error = ""
        restore_error = ""
        try:
            self.capture_self_test_update("Stopping the current replay buffer...", 5)
            if self.manager.replay_proc and self.manager.replay_proc.poll() is None:
                self.manager.stop_replay()
                time.sleep(0.8)

            test_config = json.loads(json.dumps(original_config))
            test_config["clip_seconds"] = int(test_seconds)
            test_config["segment_seconds"] = min(4, int(test_config.get("segment_seconds", 4) or 4))
            test_config["reset_replay_after_clip"] = False
            test_config["obs_replay_ram_auto"] = True
            test_config["obs_replay_buffer_mb"] = recommended_obs_replay_buffer_mb(
                test_seconds,
                test_config.get("video_bitrate_mbps", DEFAULT_CONFIG["video_bitrate_mbps"]),
            )
            self.manager.update_config(test_config)
            self.capture_self_test_update("Starting a fresh 10-second replay buffer...", 10)
            self.manager.start_replay()
            test_started_replay = True
            time.sleep(1.0)
            if not self.manager.replay_proc or self.manager.replay_proc.poll() is not None:
                raise RuntimeError("Replay buffer did not remain active after startup.")

            wait_seconds = test_seconds + 2
            for elapsed in range(wait_seconds):
                if not self.manager.replay_proc or self.manager.replay_proc.poll() is not None:
                    raise RuntimeError("Replay buffer stopped during the test countdown.")
                remaining = max(0, wait_seconds - elapsed)
                self.capture_self_test_update(
                    f"Capturing fresh video and audio... {remaining}s",
                    15 + (elapsed / max(1, wait_seconds)) * 55,
                )
                time.sleep(1.0)

            self.capture_self_test_update("Saving the test replay clip...", 72)
            save_started_at = time.time()
            previous_path = str(self.manager.last_clip_path or "")
            self.manager.save_clip()
            candidate = Path(self.manager.last_clip_path) if self.manager.last_clip_path else None
            if not candidate or not candidate.exists():
                raise RuntimeError("The replay buffer did not produce a saved clip.")
            try:
                is_new = candidate.stat().st_mtime >= save_started_at - 2.0
            except OSError:
                is_new = False
            if str(candidate) == previous_path and not is_new:
                raise RuntimeError("ShadowClip still points to the previous clip after saving.")
            clip_path = self.capture_self_test_clip_path(candidate)
            self.threadsafe_log(f"Capture self-test clip saved: {clip_path}")
        except Exception as exc:
            capture_error = str(exc)
            self.threadsafe_log(f"Capture self-test recording failed: {capture_error}")
        finally:
            self.capture_self_test_update("Restoring your previous capture state...", 80)
            if test_started_replay and self.manager.replay_proc and self.manager.replay_proc.poll() is None:
                try:
                    self.manager.stop_replay()
                except Exception as exc:
                    restore_error = f"Could not stop the temporary replay buffer: {exc}"
            self.manager.update_config(original_config)
            if replay_was_running:
                try:
                    self.manager.start_replay()
                except Exception as exc:
                    suffix = f"; {exc}" if restore_error else str(exc)
                    restore_error = (restore_error + suffix).strip("; ")
                    self.threadsafe_log(f"Capture self-test replay restore failed: {exc}")

        self.capture_self_test_update("Inspecting video, audio, and timing...", 88)
        if clip_path:
            result = self.analyze_capture_self_test_clip(clip_path, expected)
        else:
            checks = []
            self.capture_self_test_check(
                checks,
                "error",
                "Replay save",
                capture_error or "No test clip was created.",
                "Run Check setup, verify OBS and FFmpeg, then export a debug report if the problem remains.",
            )
            result = {
                "path": "",
                "checks": checks,
                "expected": expected,
                "metadata": {},
            }
        if restore_error:
            self.capture_self_test_check(
                result["checks"],
                "warn",
                "Replay state restore",
                restore_error,
                "Start Instant Replay manually once the test window closes.",
            )
        elif replay_was_running:
            self.capture_self_test_check(result["checks"], "ok", "Replay state restore", "Instant Replay was restarted with the original settings.")
        else:
            self.capture_self_test_check(result["checks"], "ok", "Replay state restore", "Instant Replay remains stopped, matching its state before the test.")
        result["summary"] = self.capture_self_test_summary(result["checks"])
        result["capture_error"] = capture_error
        self.capture_self_test_update("Test complete.", 100)
        try:
            self.root.after(250, lambda data=result: self.finish_capture_self_test(data))
        except (tk.TclError, RuntimeError):
            pass

    def finish_capture_self_test(self, result):
        self.capture_self_test_running = False
        self.capture_self_test_last_result = result
        self.close_capture_self_test_window()
        summary = result.get("summary") or self.capture_self_test_summary(result.get("checks") or [])
        self.threadsafe_log(
            f"Capture self-test finished: {summary['ok']} OK, {summary['warn']} warning(s), {summary['error']} error(s)."
        )
        self.refresh_status_panel()
        self.refresh_clip_library(force=True)
        self.show_capture_self_test_results(result)

    def close_capture_self_test_results(self):
        window = getattr(self, "capture_self_test_results_window", None)
        self.capture_self_test_results_window = None
        if window and window.winfo_exists():
            window.destroy()

    def show_capture_self_test_results(self, result):
        self.close_capture_self_test_results()
        colors = self.ui_colors
        checks = result.get("checks") or []
        summary = result.get("summary") or self.capture_self_test_summary(checks)
        if summary["error"]:
            accent = "#ff6b6b"
            title = "Capture test needs attention"
            subtitle = f"{summary['error']} error(s) and {summary['warn']} warning(s) were found."
        elif summary["warn"]:
            accent = "#f5b942"
            title = "Capture works with warnings"
            subtitle = f"The test passed with {summary['warn']} item(s) worth checking."
        else:
            accent = colors["accent"]
            title = "Capture test passed"
            subtitle = "Video, timing, and the configured audio path look ready."

        window = tk.Toplevel(self.root)
        self.capture_self_test_results_window = window
        window.title(f"{APP_NAME} Capture Test Results")
        window.configure(bg=colors["bg"])
        window.minsize(780, 620)
        window.geometry("860x700")
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self.close_capture_self_test_results)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        header = tk.Frame(window, bg=colors["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 16))
        header.columnconfigure(1, weight=1)
        badge = tk.Label(header, text="✓" if not summary["error"] else "!", width=3, bg=accent, fg="#071007", font=("Segoe UI", 16, "bold"))
        badge.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 14), ipady=6)
        tk.Label(header, text=title, bg=colors["bg"], fg=colors["text"], font=("Segoe UI", 20, "bold"), anchor="w").grid(row=0, column=1, sticky="ew")
        tk.Label(header, text=subtitle, bg=colors["bg"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w").grid(row=1, column=1, sticky="ew", pady=(3, 0))

        host = tk.Frame(window, bg=colors["bg"])
        host.grid(row=1, column=0, sticky="nsew", padx=28)
        host.columnconfigure(0, weight=1)
        host.rowconfigure(0, weight=1)
        canvas = tk.Canvas(host, bg=colors["bg"], highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        canvas.configure(yscrollcommand=scrollbar.set)
        body = tk.Frame(canvas, bg=colors["bg"])
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")), add="+")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=max(1, event.width)), add="+")
        palette = {"ok": colors["accent"], "warn": "#f5b942", "error": "#ff6b6b"}
        for check in checks:
            panel = self.dashboard_panel(body)
            panel.pack(fill="x", pady=5)
            panel.columnconfigure(1, weight=1)
            level = str(check.get("level") or "warn")
            color = palette.get(level, colors["muted"])
            tk.Label(panel, text="●", bg=colors["panel"], fg=color, font=("Segoe UI", 13)).grid(row=0, column=0, rowspan=3, padx=(16, 12), pady=13)
            tk.Label(panel, text=check.get("name", "Check"), bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 10, "bold"), anchor="w").grid(row=0, column=1, sticky="ew", pady=(12, 0))
            tk.Label(panel, text=check.get("detail", ""), bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=650).grid(row=1, column=1, sticky="ew", pady=(2, 0))
            if check.get("suggestion"):
                tk.Label(panel, text=check["suggestion"], bg=colors["panel"], fg=color, font=("Segoe UI", 8, "bold"), anchor="w", justify="left", wraplength=650).grid(row=2, column=1, sticky="ew", pady=(3, 12))
            else:
                tk.Frame(panel, bg=colors["panel"], height=10).grid(row=2, column=1, sticky="ew")

        def scroll(event):
            canvas.yview_scroll((-1 if event.delta > 0 else 1) * 3, "units")
            return "break"
        canvas.bind("<MouseWheel>", scroll, add="+")
        body.bind("<MouseWheel>", scroll, add="+")

        def bind_result_scroll_tree():
            if not body.winfo_exists():
                return
            stack = [body]
            while stack:
                widget = stack.pop()
                widget.bind("<MouseWheel>", scroll, add="+")
                stack.extend(widget.winfo_children())

        self.root.after_idle(bind_result_scroll_tree)

        footer = tk.Frame(window, bg=colors["bg_soft"], height=76, highlightbackground=colors["border_soft"], highlightthickness=1)
        footer.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        footer.grid_propagate(False)
        footer.columnconfigure(0, weight=1)
        path = Path(result.get("path")) if result.get("path") else None
        if path and path.exists():
            self.small_action_button(footer, "Open test clip", lambda p=path: self.play_clip_path(p), icon_key="clips").grid(row=0, column=1, padx=(10, 7), pady=18)
            self.small_action_button(footer, "Show in folder", lambda p=path: self.reveal_clip_path(p), icon_key="folder").grid(row=0, column=2, padx=7, pady=18)
        self.small_action_button(footer, "Run again", lambda: (self.close_capture_self_test_results(), self.run_capture_self_test()), icon_key="replay").grid(row=0, column=3, padx=7, pady=18)
        self.small_action_button(footer, "Close", self.close_capture_self_test_results, accent=True, icon_key="check").grid(row=0, column=4, padx=(7, 22), pady=18)
        window.lift()

    def build_updates_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.build_settings_page_header(parent, "Updates", "Keep ShadowClip current and collect diagnostics when something goes wrong", save=False)
        content = self.create_scrollable_settings_content(parent)
        content.columnconfigure(0, weight=1)
        actions = tk.Frame(content, bg=colors["bg"])
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="update_actions")
        self.make_action_card(actions, "updates", "Check for updates", "Download the latest release", self.check_for_updates).grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 14))
        self.make_action_card(actions, "settings", "Setup wizard", "Configure this PC again", self.show_setup_wizard).grid(row=0, column=1, sticky="nsew", padx=7, pady=(0, 14))
        self.make_action_card(actions, "record", "Capture test", "Test video, audio, and timing", self.run_capture_self_test).grid(row=0, column=2, sticky="nsew", padx=(7, 0), pady=(0, 14))
        self.make_action_card(actions, "check", "Check setup", "Verify capture dependencies", self.run_health_check).grid(row=1, column=0, sticky="nsew", padx=(0, 7))
        self.make_action_card(actions, "logs", "Beta report", "Export privacy-safe diagnostics", self.export_debug_report).grid(row=1, column=1, sticky="nsew", padx=7)

        operations, body = self.create_settings_panel(content, "Application controls", "Common maintenance actions for the current ShadowClip session.", "settings")
        operations.grid(row=1, column=0, sticky="ew")
        for column in range(3):
            body.columnconfigure(column, weight=1)
        self.small_action_button(body, "Save settings", self.save_settings, icon_key="check").grid(row=0, column=0, sticky="ew", padx=(0, 7))
        self.small_action_button(body, "Hide to tray", self.hide_window, icon_key="open").grid(row=0, column=1, sticky="ew", padx=7)
        self.small_action_button(body, "Stop all capture", self.stop_all, icon_key="record").grid(row=0, column=2, sticky="ew", padx=(7, 0))

        beta, beta_body = self.create_settings_panel(content, "Beta diagnostics", "Use the anonymous support ID when sharing a report with testers or opening an issue.", "logs")
        beta.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        beta_body.columnconfigure(0, weight=1)
        beta_body.columnconfigure(1, weight=0)
        beta_body.columnconfigure(2, weight=0)
        support_id = self.beta_support_id()
        tk.Label(beta_body, text=support_id, bg=colors["panel"], fg=colors["accent"], font=("Consolas", 12, "bold"), anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(beta_body, text="Personal Windows paths, user/computer names, and window titles are redacted before export.", bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=480).grid(row=1, column=0, sticky="ew", pady=(3, 0))
        self.small_action_button(beta_body, "Copy ID", self.copy_beta_support_id, icon_key="open").grid(row=0, column=1, rowspan=2, padx=(18, 7), sticky="e")
        self.small_action_button(beta_body, "Export", self.export_debug_report, accent=True, icon_key="logs").grid(row=0, column=2, rowspan=2, padx=(7, 0), sticky="e")

    def build_logs_page(self, parent):
        colors = self.ui_colors
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.build_settings_page_header(parent, "Logs", "Inspect runtime events, capture diagnostics, and updater messages", save=False)
        logs, body = self.create_settings_panel(parent, "Runtime log", "New events appear here while ShadowClip is running.", "logs")
        logs.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)
        toolbar = tk.Frame(body, bg=colors["panel"])
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(0, weight=1)
        self.small_action_button(toolbar, "Export debug report", self.export_debug_report, icon_key="open").grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.small_action_button(toolbar, "Clear", self.clear_log_view, icon_key="trash").grid(row=0, column=2, sticky="e")
        self.log_text = tk.Text(
            body,
            height=18,
            wrap="word",
            state="disabled",
            bg="#080a0d",
            fg="#dbe5f1",
            insertbackground="#dbe5f1",
            selectbackground=self.ui_colors["accent_dark"],
            relief="flat",
            bd=0,
            font=("Consolas", 9),
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def bind_status_traces(self):
        watched = [
            "capture_mode",
            "monitor_index",
            "window_title",
            "capture_desktop_overlays",
            "mic_enabled",
            "desktop_audio_enabled",
            "organize_clips_by_game",
            "max_storage_gb",
        ]
        for key in watched:
            self.vars[key].trace_add("write", lambda *args: self.refresh_status_panel())
        for key in ("framerate", "capture_mode", "capture_backend", "monitor_index", "auto_video_bitrate", "auto_bitrate_preset"):
            self.vars[key].trace_add("write", self.sync_auto_video_bitrate)
        for key in ("clip_seconds", "video_bitrate_mbps", "obs_replay_ram_auto"):
            self.vars[key].trace_add("write", self.sync_auto_obs_replay_buffer)
        for variable in self.vars.values():
            variable.trace_add("write", self.mark_settings_dirty)
        for variable in self.hotkey_vars.values():
            variable.trace_add("write", self.mark_settings_dirty)

    def video_dimensions_for_config(self, config):
        monitors = self.monitors or enum_monitors()
        if not monitors:
            return 1920, 1080
        mode = str(config.get("capture_mode") or DEFAULT_CONFIG["capture_mode"])
        backend = str(config.get("capture_backend") or DEFAULT_CONFIG["capture_backend"]).casefold()
        if mode == "desktop_all" and backend != "obs" and len(monitors) > 1:
            left = min(int(monitor["left"]) for monitor in monitors)
            top = min(int(monitor["top"]) for monitor in monitors)
            right = max(int(monitor["left"]) + int(monitor["width"]) for monitor in monitors)
            bottom = max(int(monitor["top"]) + int(monitor["height"]) for monitor in monitors)
            return max(320, right - left), max(240, bottom - top)
        try:
            index = int(config.get("monitor_index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
        index = max(0, min(index, len(monitors) - 1))
        monitor = monitors[index]
        return int(monitor["width"]), int(monitor["height"])

    def video_dimensions_for_bitrate(self):
        return self.video_dimensions_for_config({
            "capture_mode": self.vars["capture_mode"].get(),
            "capture_backend": self.vars["capture_backend"].get(),
            "monitor_index": self.vars["monitor_index"].get(),
        })

    def calculated_auto_video_bitrate(self):
        width, height = self.video_dimensions_for_bitrate()
        preset = normalize_auto_bitrate_preset(self.vars["auto_bitrate_preset"].get())
        target = recommended_video_bitrate_mbps(
            self.vars["framerate"].get(),
            width,
            height,
            preset,
        )
        maximum = recommended_max_bitrate_mbps(target, preset)
        return target, maximum

    def sync_auto_video_bitrate(self, *args, force=False):
        if self.updating_auto_video_bitrate:
            return
        auto_enabled = bool(self.vars["auto_video_bitrate"].get())
        preset_state = "readonly" if auto_enabled else "disabled"
        bitrate_state = "disabled" if auto_enabled else "normal"
        mode_state = "disabled" if auto_enabled else "readonly"
        widget_states = {
            "auto_bitrate_preset_combo": preset_state,
            "auto_bitrate_preset_combo_overlay": preset_state,
            "bitrate_mode_combo": mode_state,
            "bitrate_mode_combo_overlay": mode_state,
            "video_bitrate_spin": bitrate_state,
            "video_bitrate_spin_overlay": bitrate_state,
            "max_bitrate_spin": bitrate_state,
            "max_bitrate_spin_overlay": bitrate_state,
        }
        for widget_name, state in widget_states.items():
            widget = getattr(self, widget_name, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except tk.TclError:
                    pass
        if not auto_enabled:
            return
        preset = normalize_auto_bitrate_preset(self.vars["auto_bitrate_preset"].get())
        target, maximum = self.calculated_auto_video_bitrate()
        self.updating_auto_video_bitrate = True
        try:
            if self.vars["auto_bitrate_preset"].get() != preset:
                self.vars["auto_bitrate_preset"].set(preset)
            self.vars["bitrate_mode"].set("target")
            self.vars["video_bitrate_mbps"].set(target)
            self.vars["max_bitrate_mbps"].set(maximum)
        finally:
            self.updating_auto_video_bitrate = False
        self.sync_auto_obs_replay_buffer(force=True)

    def calculated_obs_replay_buffer_mb(self):
        return recommended_obs_replay_buffer_mb(
            self.vars["clip_seconds"].get(),
            self.vars["video_bitrate_mbps"].get(),
        )

    def sync_auto_obs_replay_buffer(self, *args, force=False):
        if self.updating_auto_replay_ram:
            return
        auto_enabled = bool(self.vars["obs_replay_ram_auto"].get())
        state = "disabled" if auto_enabled else "normal"
        for widget_name in ("obs_replay_buffer_spin", "obs_replay_buffer_spin_overlay"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except tk.TclError:
                    pass
        if not auto_enabled:
            return
        target = self.calculated_obs_replay_buffer_mb()
        try:
            current = int(self.vars["obs_replay_buffer_mb"].get())
        except (TypeError, ValueError, tk.TclError):
            current = 0
        if current == target:
            return
        self.updating_auto_replay_ram = True
        try:
            self.vars["obs_replay_buffer_mb"].set(target)
        finally:
            self.updating_auto_replay_ram = False

    def collect_hotkey_config(self):
        hotkeys = {}
        for action, _label in HOTKEY_ACTIONS:
            value = self.hotkey_vars[action].get().strip()
            hotkeys[action] = parse_hotkey_text(value)[2]
        return hotkeys

    def validate_hotkeys(self, hotkeys):
        used = {}
        normalized = {}
        for action, label in HOTKEY_ACTIONS:
            value = hotkeys.get(action, "")
            try:
                modifiers, key, text = parse_hotkey_text(value)
            except ValueError as exc:
                return None, f"{label}: {exc}"
            signature = (modifiers, key)
            if signature in used:
                return None, f"{label}: {text} is already used by {used[signature]}."
            used[signature] = label
            normalized[action] = text
        return normalized, ""

    def reset_hotkeys_to_defaults(self):
        for action, _label in HOTKEY_ACTIONS:
            self.hotkey_vars[action].set(DEFAULT_CONFIG["hotkeys"][action])
        self.threadsafe_log("Hotkeys reset to standalone defaults. Click Save Hotkeys to apply.")

    def hotkey_label(self, action):
        var = self.hotkey_vars.get(action)
        if var:
            return var.get()
        return DEFAULT_CONFIG["hotkeys"].get(action, "")

    def normalized_game_profiles(self, profiles):
        if not isinstance(profiles, dict):
            return {}
        clean_profiles = {}
        for raw_key, raw_profile in profiles.items():
            if not isinstance(raw_profile, dict):
                continue
            key = sanitize_path_part(raw_key, "")
            if not key:
                continue
            settings = raw_profile.get("settings", {})
            if not isinstance(settings, dict):
                continue
            clean_settings = {
                setting_key: settings[setting_key]
                for setting_key in GAME_PROFILE_SETTING_KEYS
                if setting_key in settings
            }
            if not clean_settings:
                continue
            label = sanitize_path_part(raw_profile.get("label") or raw_profile.get("process") or key, key)
            clean_profiles[key.casefold()] = {
                "label": label,
                "process": str(raw_profile.get("process", "")),
                "title": str(raw_profile.get("title", "")),
                "updated_at": str(raw_profile.get("updated_at", "")),
                "settings": clean_settings,
            }
        return clean_profiles

    def profile_key_from_label(self, label):
        key = process_name_key(label)
        if not key:
            key = sanitize_path_part(label, "").casefold()
        return key[:80]

    def game_profile_identity_from_context(self, context):
        if not isinstance(context, dict):
            return None
        process_name = str(context.get("process") or "").strip()
        title = str(context.get("title") or "").strip()
        display_label = title or process_name
        label = friendly_application_name(process_name, title, display_label)
        key = self.profile_key_from_label(process_name or title)
        if not key:
            return None
        return {
            "key": key,
            "label": label or key,
            "process": process_name,
            "title": title,
        }

    def current_game_profile_identity(self):
        context = foreground_window_basic_context()
        identity = self.game_profile_identity_from_context(context)
        if identity:
            return identity

        if self.vars["capture_mode"].get() == "window":
            title = self.vars["window_title"].get().strip()
            hwnd = find_window_by_title(title)
            process_name = window_process_name(hwnd) if hwnd else ""
            identity = self.game_profile_identity_from_context({
                "process": process_name,
                "title": title,
            })
            if identity:
                return identity

        cached = self.manager.cached_game_capture_label()
        if cached:
            key = self.profile_key_from_label(cached)
            if key:
                return {
                    "key": key,
                    "label": sanitize_path_part(cached, key),
                    "process": cached,
                    "title": "",
                }
        return None

    def game_profile_settings_from_config(self, config):
        settings = {}
        for key in GAME_PROFILE_SETTING_KEYS:
            if key in config:
                settings[key] = config[key]
        return settings

    def set_var_from_profile_value(self, key, value):
        var = self.vars.get(key)
        if var is None:
            return
        try:
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            elif isinstance(var, tk.IntVar):
                var.set(int(value))
            elif isinstance(var, tk.DoubleVar):
                var.set(float(value))
            else:
                var.set(str(value))
        except (tk.TclError, TypeError, ValueError):
            pass

    def apply_game_profile_for_current_game(self, reason="capture"):
        if not bool(self.vars["use_game_profiles"].get()):
            self.last_applied_game_profile_key = ""
            return False
        identity = self.current_game_profile_identity()
        if not identity:
            return False
        profiles = self.normalized_game_profiles(self.config.get("game_profiles", {}))
        profile = profiles.get(identity["key"])
        if not profile:
            return False
        settings = profile.get("settings", {})
        if not settings:
            return False

        changed = []
        for key in GAME_PROFILE_SETTING_KEYS:
            if key not in settings:
                continue
            before = self.vars[key].get() if key in self.vars else self.config.get(key)
            self.set_var_from_profile_value(key, settings[key])
            after = self.vars[key].get() if key in self.vars else settings[key]
            if before != after:
                changed.append(key)

        config = self.collect_config()
        self.config["game_profiles"] = profiles
        self.manager.update_config(self.config)
        self.sync_auto_obs_replay_buffer(force=True)
        label = profile.get("label") or identity.get("label") or identity["key"]
        signature = f"{identity['key']}:{json.dumps(settings, sort_keys=True, ensure_ascii=False)}"
        if changed or self.last_applied_game_profile_key != signature:
            self.threadsafe_log(f"Game profile applied for {label}: {reason}.")
            self.last_applied_game_profile_key = signature
        return True

    def prepare_capture_action(self, reason):
        self.collect_config()
        self.apply_game_profile_for_current_game(reason=reason)

    def save_game_profile_for_current_game(self):
        config = self.collect_config()
        identity = self.current_game_profile_identity()
        if not identity:
            message = "No game/app context detected. Focus a game once, or select a Window/Game title, then try again."
            self.threadsafe_log(f"Game profile not saved: {message}")
            messagebox.showwarning(APP_NAME, message)
            return

        profiles = self.normalized_game_profiles(config.get("game_profiles", {}))
        profiles[identity["key"]] = {
            "label": identity["label"],
            "process": identity.get("process", ""),
            "title": identity.get("title", ""),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "settings": self.game_profile_settings_from_config(config),
        }
        config["game_profiles"] = profiles
        config["use_game_profiles"] = bool(config.get("use_game_profiles", True))
        self.config = config
        self.manager.update_config(config)
        save_config(config)
        self.threadsafe_log(f"Game profile saved for {identity['label']} ({len(profiles)} profile(s)).")
        self.clear_settings_dirty()

    def delete_game_profile_for_current_game(self):
        self.collect_config()
        identity = self.current_game_profile_identity()
        if not identity:
            message = "No game/app context detected for profile deletion."
            self.threadsafe_log(f"Game profile not deleted: {message}")
            messagebox.showwarning(APP_NAME, message)
            return
        profiles = self.normalized_game_profiles(self.config.get("game_profiles", {}))
        removed = profiles.pop(identity["key"], None)
        if not removed:
            message = f"No saved profile for {identity['label']}."
            self.threadsafe_log(message)
            messagebox.showinfo(APP_NAME, message)
            return
        self.config["game_profiles"] = profiles
        self.manager.update_config(self.config)
        save_config(self.config)
        self.last_applied_game_profile_key = ""
        self.threadsafe_log(f"Game profile deleted for {removed.get('label') or identity['label']}.")

    def collect_config(self):
        config = self.config.copy()
        try:
            config["hotkeys"] = self.collect_hotkey_config()
        except ValueError:
            config["hotkeys"] = self.config.get("hotkeys", DEFAULT_CONFIG["hotkeys"]).copy()
        for key, var in self.vars.items():
            value = var.get()
            if key in {
                "framerate",
                "clip_seconds",
                "segment_seconds",
                "monitor_index",
                "quality",
                "audio_offset_ms",
                "recording_audio_offset_ms",
                "toast_duration_ms",
                "gallery_limit",
                "video_bitrate_mbps",
                "max_bitrate_mbps",
                "obs_replay_buffer_mb",
            }:
                value = int(value)
            elif key in {"max_storage_gb"}:
                value = float(value)
            config[key] = value
        config["capture_desktop_overlays"] = bool(
            config.get("capture_desktop_overlays", DEFAULT_CONFIG["capture_desktop_overlays"])
        )
        config["capture_desktop_overlays_migrated"] = True
        if config["capture_desktop_overlays"]:
            config["capture_backend"] = "obs"
            self.vars["capture_backend"].set("obs")
        if config.get("mic_enabled") and config.get("mic_device"):
            config["audio_mode"] = "dshow"
            config["audio_device"] = config["mic_device"]
        elif config.get("desktop_audio_enabled") and config.get("desktop_audio_device"):
            config["audio_mode"] = "dshow"
            config["audio_device"] = config["desktop_audio_device"]
        else:
            config["audio_mode"] = "none"
        config["toast_duration_ms"] = max(500, min(10000, int(config.get("toast_duration_ms", 2600) or 2600)))
        config["gallery_limit"] = max(3, min(50, int(config.get("gallery_limit", 12) or 12)))
        config["video_bitrate_mbps"] = max(1, min(300, int(config.get("video_bitrate_mbps", 35) or 35)))
        config["max_bitrate_mbps"] = max(config["video_bitrate_mbps"], min(500, int(config.get("max_bitrate_mbps", 50) or 50)))
        config["auto_video_bitrate"] = bool(config.get("auto_video_bitrate", DEFAULT_CONFIG["auto_video_bitrate"]))
        config["auto_bitrate_preset"] = normalize_auto_bitrate_preset(config.get("auto_bitrate_preset", DEFAULT_CONFIG["auto_bitrate_preset"]))
        if config["auto_video_bitrate"]:
            width, height = self.video_dimensions_for_config(config)
            target_bitrate = recommended_video_bitrate_mbps(
                config.get("framerate", DEFAULT_CONFIG["framerate"]),
                width,
                height,
                config["auto_bitrate_preset"],
            )
            config["bitrate_mode"] = "target"
            config["video_bitrate_mbps"] = target_bitrate
            config["max_bitrate_mbps"] = recommended_max_bitrate_mbps(target_bitrate, config["auto_bitrate_preset"])
            self.updating_auto_video_bitrate = True
            try:
                self.vars["auto_bitrate_preset"].set(config["auto_bitrate_preset"])
                self.vars["bitrate_mode"].set(config["bitrate_mode"])
                self.vars["video_bitrate_mbps"].set(config["video_bitrate_mbps"])
                self.vars["max_bitrate_mbps"].set(config["max_bitrate_mbps"])
            finally:
                self.updating_auto_video_bitrate = False
        config["obs_replay_ram_auto"] = bool(config.get("obs_replay_ram_auto", DEFAULT_CONFIG["obs_replay_ram_auto"]))
        config["obs_replay_buffer_mb"] = max(64, min(2048, int(config.get("obs_replay_buffer_mb", DEFAULT_CONFIG["obs_replay_buffer_mb"]) or DEFAULT_CONFIG["obs_replay_buffer_mb"])))
        if config["obs_replay_ram_auto"]:
            config["obs_replay_buffer_mb"] = recommended_obs_replay_buffer_mb(
                config.get("clip_seconds", DEFAULT_CONFIG["clip_seconds"]),
                config.get("video_bitrate_mbps", DEFAULT_CONFIG["video_bitrate_mbps"]),
            )
            self.vars["obs_replay_buffer_mb"].set(config["obs_replay_buffer_mb"])
        if config.get("bitrate_mode") not in {"quality", "target"}:
            config["bitrate_mode"] = "quality"
        config["video_encoder"] = normalize_video_encoder(config.get("video_encoder"))
        if config.get("obs_minecraft_capture_mode") not in {"specific_game", "display", "any_fullscreen"}:
            config["obs_minecraft_capture_mode"] = DEFAULT_CONFIG["obs_minecraft_capture_mode"]
        if config.get("toast_position") not in {"top_right", "bottom_right", "top_left", "bottom_left"}:
            config["toast_position"] = "top_right"
        config["use_game_profiles"] = bool(config.get("use_game_profiles", DEFAULT_CONFIG["use_game_profiles"]))
        config["game_profiles"] = self.normalized_game_profiles(config.get("game_profiles", {}))
        self.config = config
        self.manager.update_config(config)
        self.refresh_status_panel()
        return config

    def save_settings(self):
        normalized_hotkeys, error = self.validate_hotkeys({action: var.get() for action, var in self.hotkey_vars.items()})
        if error:
            self.threadsafe_log(f"Settings not saved: {error}")
            try:
                messagebox.showerror(APP_NAME, f"Invalid hotkey:\n{error}")
            except tk.TclError:
                pass
            return False
        for action, value in normalized_hotkeys.items():
            self.hotkey_vars[action].set(value)
        old_hotkeys = self.config.get("hotkeys", DEFAULT_CONFIG["hotkeys"]).copy()
        config = self.collect_config()
        save_config(config)
        self.apply_autostart(bool(config.get("start_with_windows", False)))
        self.manager.cleanup_output_storage()
        if config.get("hotkeys") != old_hotkeys:
            self.restart_hotkeys(config["hotkeys"])
        self.threadsafe_log(f"Settings saved: {CONFIG_PATH}")
        self.clear_settings_dirty()
        return True

    def restart_hotkeys(self, hotkeys):
        old_thread = self.hotkeys
        if old_thread:
            old_thread.stop()
            old_thread.join(timeout=1.5)
        self.hotkeys = HotkeyThread(self.dispatch_hotkey, self.threadsafe_log, hotkeys)
        self.hotkeys.start()
        self.update_overlay_state()

    def autostart_command(self):
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --minimized'
        script = Path(__file__).resolve()
        return f'"{sys.executable}" "{script}" --minimized'

    def apply_autostart(self, enabled):
        if os.name != "nt":
            return
        try:
            remove_legacy_startup_shortcut()
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, self.autostart_command())
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
            state = "enabled" if enabled else "disabled"
            self.threadsafe_log(f"Windows autostart {state}.")
        except Exception as exc:
            self.threadsafe_log(f"Windows autostart update failed: {exc}")

    def refresh_monitors(self):
        self.monitors = enum_monitors()
        labels = [monitor_label(monitor) for monitor in self.monitors]
        combos = [self.monitor_combo, getattr(self, "monitor_combo_overlay", None)]
        for combo in combos:
            if not combo:
                continue
            try:
                combo["values"] = labels
            except tk.TclError:
                pass
        if labels:
            index = max(0, min(int(self.vars["monitor_index"].get()), len(labels) - 1))
            for combo in combos:
                if not combo:
                    continue
                try:
                    combo.current(index)
                except tk.TclError:
                    pass

    def on_monitor_selected(self, event=None):
        combo = event.widget if event is not None else self.monitor_combo
        selected = combo.current()
        if selected >= 0:
            self.vars["monitor_index"].set(selected)

    def refresh_windows(self):
        self.windows = enum_windows()
        combos = [self.window_combo, getattr(self, "window_combo_overlay", None)]
        for combo in combos:
            if not combo:
                continue
            try:
                combo["values"] = self.windows
            except tk.TclError:
                pass
        self.threadsafe_log(f"Window list refreshed ({len(self.windows)} visible titles).")

    def scan_audio(self):
        self.collect_config()
        try:
            devices, raw = self.manager.scan_audio_devices()
            wasapi_loopbacks = self.manager.scan_wasapi_loopbacks()
            wasapi_mics = self.manager.scan_soundcard_mics()
            self.audio_devices = devices
            mic_devices = sorted(set(devices + wasapi_mics), key=str.casefold)
            mic_combos = [self.mic_combo, getattr(self, "mic_combo_overlay", None)]
            for combo in mic_combos:
                if not combo:
                    continue
                try:
                    combo["values"] = mic_devices
                except tk.TclError:
                    pass
            desktop_devices = wasapi_loopbacks
            if self.vars["desktop_audio_backend"].get() == "dshow":
                desktop_devices = [device for device in devices if looks_like_desktop_audio_device(device)]
            desktop_combos = [self.desktop_audio_combo, getattr(self, "desktop_audio_combo_overlay", None)]
            for combo in desktop_combos:
                if not combo:
                    continue
                try:
                    combo["values"] = desktop_devices
                except tk.TclError:
                    pass
            preferred_mic = next((device for device in mic_devices if "broadcast" in device.casefold()), None)
            preferred_mic = preferred_mic or (mic_devices[0] if mic_devices else (devices[0] if devices else ""))
            if preferred_mic and not self.vars["mic_device"].get():
                self.vars["mic_device"].set(preferred_mic)
            if desktop_devices and not self.vars["desktop_audio_device"].get():
                default_desktop = desktop_devices[0]
                if sc is not None and self.vars["desktop_audio_backend"].get() == "wasapi":
                    try:
                        default_name = sc.default_speaker().name
                        default_desktop = next((device for device in desktop_devices if device == default_name), default_desktop)
                    except Exception:
                        pass
                self.vars["desktop_audio_device"].set(default_desktop)
            self.threadsafe_log(f"Audio scan found {len(devices)} DirectShow devices, {len(wasapi_mics)} WASAPI mics, and {len(wasapi_loopbacks)} WASAPI loopbacks.")
            if not devices:
                self.threadsafe_log("No DirectShow audio device found.")
            if self.vars["desktop_audio_backend"].get() == "wasapi" and not wasapi_loopbacks:
                self.threadsafe_log("No WASAPI desktop loopback device found.")
            elif self.vars["desktop_audio_backend"].get() == "dshow" and not desktop_devices:
                self.threadsafe_log("No DirectShow desktop/loopback audio device found.")
        except Exception as exc:
            self.threadsafe_log(f"Audio scan failed: {exc}")

    def browse_ffmpeg(self):
        if self.ffmpeg_picker_running:
            self.threadsafe_log("FFmpeg file picker is already open.")
            return
        self.ffmpeg_picker_running = True
        configured = self.vars["ffmpeg_path"].get().strip()
        initial_dir = str(Path(configured).parent) if configured else str(APP_DIR)
        self.threadsafe_log("Opening FFmpeg file picker...")
        thread = threading.Thread(target=self.browse_ffmpeg_worker, args=(initial_dir,), daemon=True)
        thread.start()

    def browse_ffmpeg_worker(self, initial_dir):
        path = ""
        try:
            path = browse_file_powershell(
                "Select ffmpeg.exe",
                "ffmpeg.exe|ffmpeg.exe|Executables (*.exe)|*.exe|All files (*.*)|*.*",
                initial_dir=initial_dir,
            )
            if path:
                self.root.after(0, lambda selected=path: self.set_ffmpeg_path(selected))
            else:
                self.threadsafe_log("FFmpeg file picker closed.")
        except Exception as exc:
            self.threadsafe_log(f"FFmpeg file picker failed: {exc}")
        finally:
            self.root.after(0, self.finish_ffmpeg_picker)

    def set_ffmpeg_path(self, path):
        self.vars["ffmpeg_path"].set(path)
        self.threadsafe_log(f"FFmpeg selected: {path}")

    def finish_ffmpeg_picker(self):
        self.ffmpeg_picker_running = False

    def browse_obs(self):
        if self.obs_picker_running:
            self.threadsafe_log("OBS file picker is already open.")
            return
        self.obs_picker_running = True
        configured = self.vars["obs_path"].get().strip()
        initial_dir = str(Path(configured).parent) if configured else str(APP_DIR)
        self.threadsafe_log("Opening OBS file picker...")
        thread = threading.Thread(target=self.browse_obs_worker, args=(initial_dir,), daemon=True)
        thread.start()

    def browse_obs_worker(self, initial_dir):
        path = ""
        try:
            path = browse_file_powershell(
                "Select obs64.exe",
                "obs64.exe|obs64.exe|Executables (*.exe)|*.exe|All files (*.*)|*.*",
                initial_dir=initial_dir,
            )
            if path:
                self.root.after(0, lambda selected=path: self.set_obs_path(selected))
            else:
                self.threadsafe_log("OBS file picker closed.")
        except Exception as exc:
            self.threadsafe_log(f"OBS file picker failed: {exc}")
        finally:
            self.root.after(0, self.finish_obs_picker)

    def set_obs_path(self, path):
        self.vars["obs_path"].set(path)
        self.threadsafe_log(f"OBS selected: {path}")

    def finish_obs_picker(self):
        self.obs_picker_running = False

    def browse_output(self):
        if self.output_picker_running:
            self.threadsafe_log("Output folder picker is already open.")
            return
        self.output_picker_running = True
        initial_dir = self.vars["output_dir"].get()
        self.threadsafe_log("Opening output folder picker...")
        thread = threading.Thread(target=self.browse_output_worker, args=(initial_dir,), daemon=True)
        thread.start()

    def browse_output_worker(self, initial_dir):
        path = ""
        try:
            try:
                path = browse_directory_powershell("Select output folder", initial_dir=initial_dir)
            except Exception as first_exc:
                self.threadsafe_log(f"PowerShell folder picker failed; trying Win32 picker: {first_exc}")
                path = browse_directory_win32("Select output folder")
            if path:
                self.root.after(0, lambda selected=path: self.set_output_folder(selected))
            else:
                self.threadsafe_log("Output folder picker closed.")
        except Exception as exc:
            self.threadsafe_log(f"Output folder picker failed: {exc}")
        finally:
            self.root.after(0, self.finish_output_picker)

    def set_output_folder(self, path):
        self.vars["output_dir"].set(path)
        self.threadsafe_log(f"Output folder selected: {path}")
        if self.health_repair_pending_output:
            self.health_repair_pending_output = False
            if self.save_settings() is not False:
                self.root.after(700, self.run_health_check)

    def finish_output_picker(self):
        self.output_picker_running = False
        self.health_repair_pending_output = False

    def open_output(self):
        self.collect_config()
        path = self.manager.output_dir()
        os.startfile(str(path))

    def clean_storage_now(self):
        self.collect_config()
        try:
            max_storage_gb = float(self.config.get("max_storage_gb", 0) or 0)
        except (TypeError, ValueError):
            max_storage_gb = 0
        if max_storage_gb <= 0:
            self.threadsafe_log("Storage cleanup is disabled. Set Max storage GB above 0 first.")
            return
        self.manager.schedule_output_storage_cleanup(force=True)
        self.threadsafe_log(f"Storage cleanup started for limit: {max_storage_gb:g} GB.")

    def diagnostic_report_dir(self):
        path = self.manager.runtime_dir / "debug_reports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def jsonable(self, value):
        return json.loads(json.dumps(value, default=str, ensure_ascii=False))

    def redacted_config(self, config):
        def redact(value):
            if isinstance(value, dict):
                clean = {}
                for key, item in value.items():
                    lowered = str(key).casefold()
                    if any(token in lowered for token in ("password", "secret", "token")):
                        clean[key] = "<redacted>"
                    else:
                        clean[key] = redact(item)
                return clean
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        return redact(self.jsonable(config))

    def beta_support_id(self):
        value = str(self.config.get("beta_install_id") or "").strip().upper()
        if not re.fullmatch(r"SC-[0-9A-F]{12}", value):
            value = f"SC-{uuid.uuid4().hex[:12].upper()}"
            self.config["beta_install_id"] = value
            save_config(self.config)
        return value

    def copy_beta_support_id(self):
        support_id = self.beta_support_id()
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(support_id)
            self.root.update_idletasks()
            self.threadsafe_log(f"Beta support ID copied: {support_id}")
            self.show_event_toast("Support ID copied", support_id, "check")
        except tk.TclError as exc:
            messagebox.showerror(APP_NAME, f"Could not copy the support ID.\n\n{exc}", parent=self.root)

    def scrub_diagnostic_text(self, value):
        text = str(value or "")
        replacements = []
        configured_paths = []
        try:
            configured_paths.append((str(expand_path(self.config.get("output_dir", DEFAULT_CONFIG["output_dir"]))), "<output-dir>"))
        except Exception:
            pass
        for key, replacement in (("ffmpeg_path", "<custom-ffmpeg>"), ("obs_path", "<custom-obs>")):
            configured = str(self.config.get(key) or "").strip()
            if configured:
                configured_paths.append((configured, replacement))
        for raw, replacement in (
            (os.environ.get("USERPROFILE", ""), "<user-profile>"),
            (os.environ.get("LOCALAPPDATA", ""), "<local-app-data>"),
            (os.environ.get("APPDATA", ""), "<app-data>"),
            (os.environ.get("USERNAME", ""), "<user>"),
            (socket.gethostname(), "<computer>"),
            (str(APP_DIR), "<shadowclip-dir>"),
        ):
            raw = str(raw or "").strip()
            if raw:
                replacements.append((raw, replacement))
        replacements.extend((raw, replacement) for raw, replacement in configured_paths if raw)
        replacements.sort(key=lambda item: len(item[0]), reverse=True)
        for raw, replacement in replacements:
            text = re.sub(re.escape(raw), replacement, text, flags=re.IGNORECASE)
        return text

    def privacy_safe_snapshot(self, snapshot):
        safe = self.jsonable(snapshot)
        safe["config"] = self.redacted_config(safe.get("config", {}))
        app = safe.get("app") or {}
        app["app_dir"] = "<shadowclip-dir>"
        app["config_path"] = "<shadowclip-dir>/shadowclip.config.json"
        app["executable"] = Path(str(app.get("executable") or "ShadowClip.exe")).name
        app["support_id"] = self.beta_support_id()
        safe["app"] = app

        system = safe.get("system") or {}
        system["hostname"] = "<redacted>"
        system["user"] = "<redacted>"
        system["local_app_data"] = "<redacted>"
        safe["system"] = system

        config = safe.get("config") or {}
        config["output_dir"] = "<output-dir>"
        config["ffmpeg_path"] = "<custom-ffmpeg>" if str(config.get("ffmpeg_path") or "").strip() else ""
        config["obs_path"] = "<custom-obs>" if str(config.get("obs_path") or "").strip() else ""
        config["window_title"] = "<redacted>" if str(config.get("window_title") or "").strip() else ""
        for profile in (config.get("game_profiles") or {}).values():
            if isinstance(profile, dict):
                profile["title"] = "<redacted>" if profile.get("title") else ""
        safe["config"] = config

        state = safe.get("state") or {}
        for key in ("recording_path", "last_clip_path"):
            raw = str(state.get(key) or "")
            state[key] = Path(raw).name if raw else ""
        foreground = state.get("foreground")
        if isinstance(foreground, dict):
            foreground.pop("hwnd", None)
            foreground["title"] = "<redacted>" if foreground.get("title") else ""
            foreground["exe"] = Path(str(foreground.get("exe") or "")).name
        identity = state.get("game_profile_identity")
        if isinstance(identity, dict):
            identity["title"] = "<redacted>" if identity.get("title") else ""
        self_test = state.get("capture_self_test_last_result")
        if isinstance(self_test, dict):
            raw_test_path = str(self_test.get("path") or "")
            self_test["path"] = Path(raw_test_path).name if raw_test_path else ""
        safe["state"] = state
        safe["window_title_count"] = len(safe.get("window_titles") or [])
        safe.pop("window_titles", None)
        safe.pop("ui_log", None)
        return json.loads(self.scrub_diagnostic_text(json.dumps(safe, ensure_ascii=False)))

    def privacy_safe_health_checks(self, checks):
        safe_checks = self.jsonable(checks)
        for check in safe_checks:
            name = str(check.get("name") or "")
            detail = self.scrub_diagnostic_text(check.get("detail") or "")
            if name == "Config":
                detail = "Configuration file detected." if check.get("level") == "ok" else "Configuration file is missing."
            elif name == "Output folder" and check.get("level") == "ok":
                detail = "Configured output folder is writable."
            elif name == "FFmpeg" and check.get("level") == "ok":
                detail = "FFmpeg runtime detected."
            elif name == "FFprobe" and check.get("level") == "ok":
                detail = "FFprobe runtime detected."
            elif name == "OBS runtime" and check.get("level") == "ok":
                detail = "OBS runtime and required capture plugins detected."
            check["detail"] = detail
            if check.get("suggestion"):
                check["suggestion"] = self.scrub_diagnostic_text(check["suggestion"])
        return safe_checks

    def current_ui_log_text(self):
        try:
            return self.log_text.get("1.0", "end-1c")
        except Exception:
            return ""

    def diagnostic_snapshot(self):
        config = self.collect_config()
        return {
            "app": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "app_dir": str(APP_DIR),
                "config_path": str(CONFIG_PATH),
                "frozen": bool(getattr(sys, "frozen", False)),
                "executable": sys.executable,
                "python": sys.version,
                "support_id": self.beta_support_id(),
            },
            "system": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "hostname": socket.gethostname(),
                "user": os.environ.get("USERNAME", ""),
                "local_app_data": os.environ.get("LOCALAPPDATA", ""),
            },
            "state": {
                "replay_running": self.replay_running(),
                "recording_running": self.recording_running(),
                "recording_elapsed": self.recording_elapsed_label(),
                "recording_size": self.recording_file_size_label(),
                "recording_path": str(self.manager.current_recording_path or ""),
                "last_clip_path": str(self.manager.last_clip_path or ""),
                "last_capture_label": str(self.manager.cached_game_capture_label() or ""),
                "obs_process_running": bool(self.manager.obs_proc and self.manager.obs_proc.poll() is None),
                "obs_capture_context": str(self.manager.obs_capture_context_key or ""),
                "obs_capture_strategy": str(self.manager.obs_capture_strategy or "auto"),
                "obs_capture_learned_strategies": len(self.manager.obs_capture_strategy_cache),
                "obs_capture_black_samples": int(self.manager.obs_capture_black_samples or 0),
                "obs_capture_recovery_pending": bool(self.manager.obs_capture_recovery_pending_reset),
                "audio_threads": {
                    key: bool(thread and thread.is_alive())
                    for key, thread in self.manager.audio_threads.items()
                },
                "foreground": foreground_window_basic_context(),
                "game_profile_identity": self.current_game_profile_identity(),
                "game_profile_count": len(self.normalized_game_profiles(config.get("game_profiles", {}))),
                "game_profiles_enabled": bool(config.get("use_game_profiles", DEFAULT_CONFIG["use_game_profiles"])),
                "capture_self_test_running": bool(self.capture_self_test_running),
                "capture_self_test_last_result": self.jsonable(self.capture_self_test_last_result) if self.capture_self_test_last_result else None,
            },
            "config": self.jsonable(config),
            "monitors": self.jsonable(enum_monitors()),
            "window_titles": list(self.windows),
            "audio_device_cache": list(self.audio_devices),
            "ui_log": self.current_ui_log_text(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

    def add_health_check(self, checks, level, name, detail, repair="", suggestion=""):
        check = {
            "level": level,
            "name": name,
            "detail": str(detail),
        }
        if repair:
            check["repair"] = str(repair)
        if suggestion:
            check["suggestion"] = str(suggestion)
        checks.append(check)

    def command_first_line(self, command, timeout=6):
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        text = (result.stdout or result.stderr or "").strip()
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if result.returncode != 0:
            raise RuntimeError(first or f"exit code {result.returncode}")
        return first

    def build_health_checks(self, snapshot):
        config = snapshot.get("config", {})
        state = snapshot.get("state", {})
        checks = []
        manager = FfmpegManager(config.copy(), lambda _message: None)

        if CONFIG_PATH.exists():
            self.add_health_check(checks, "ok", "Config", str(CONFIG_PATH))
        else:
            self.add_health_check(checks, "warn", "Config", f"Config file is missing: {CONFIG_PATH}")

        profile_count = int((snapshot.get("state") or {}).get("game_profile_count") or 0)
        profile_identity = (snapshot.get("state") or {}).get("game_profile_identity") or {}
        if bool(config.get("use_game_profiles", DEFAULT_CONFIG["use_game_profiles"])):
            if profile_identity:
                label = profile_identity.get("label") or profile_identity.get("key") or "current app"
                profiles = self.normalized_game_profiles(config.get("game_profiles", {}))
                level = "ok" if profile_identity.get("key") in profiles else "warn"
                detail = f"{profile_count} saved; current context: {label}."
                if level == "warn":
                    detail += " No saved profile for this context yet."
                self.add_health_check(checks, level, "Game profiles", detail)
            else:
                self.add_health_check(checks, "warn", "Game profiles", f"{profile_count} saved; no current game/app context detected.")
        else:
            self.add_health_check(checks, "warn", "Game profiles", f"Disabled; {profile_count} saved.")

        try:
            width, height = self.video_dimensions_for_config(config)
            preset = normalize_auto_bitrate_preset(config.get("auto_bitrate_preset", DEFAULT_CONFIG["auto_bitrate_preset"]))
            recommended_bitrate = recommended_video_bitrate_mbps(
                config.get("framerate", DEFAULT_CONFIG["framerate"]),
                width,
                height,
                preset,
            )
            recommended_max = recommended_max_bitrate_mbps(recommended_bitrate, preset)
            current_bitrate = int(config.get("video_bitrate_mbps", DEFAULT_CONFIG["video_bitrate_mbps"]) or 0)
            current_max = int(config.get("max_bitrate_mbps", DEFAULT_CONFIG["max_bitrate_mbps"]) or 0)
            fps = int(config.get("framerate", DEFAULT_CONFIG["framerate"]) or 0)
            if bool(config.get("auto_video_bitrate", DEFAULT_CONFIG["auto_video_bitrate"])):
                level = "ok" if current_bitrate == recommended_bitrate and current_max == recommended_max else "warn"
                self.add_health_check(
                    checks,
                    level,
                    "Auto bitrate",
                    f"{width}x{height} @ {fps} FPS, {preset}: {current_bitrate}/{current_max} Mbps; recommended {recommended_bitrate}/{recommended_max} Mbps.",
                    repair="sync_auto_bitrate" if level == "warn" else "",
                    suggestion="Recalculate bitrate from the current resolution and FPS." if level == "warn" else "",
                )
            else:
                self.add_health_check(
                    checks,
                    "warn",
                    "Auto bitrate",
                    f"Disabled; current target/max is {current_bitrate}/{current_max} Mbps. Recommended for {width}x{height} @ {fps} FPS, {preset}: {recommended_bitrate}/{recommended_max} Mbps.",
                    repair="enable_auto_bitrate",
                    suggestion="Enable automatic bitrate using the selected quality preset.",
                )
        except Exception as exc:
            self.add_health_check(checks, "warn", "Auto bitrate", f"Could not calculate recommendation: {exc}")

        try:
            output_dir = manager.output_dir()
            output_dir.mkdir(parents=True, exist_ok=True)
            probe = output_dir / f".shadowclip_write_test_{uuid.uuid4().hex}.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            self.add_health_check(checks, "ok", "Output folder", f"Writable: {output_dir}")
        except Exception as exc:
            self.add_health_check(checks, "error", "Output folder", f"Not writable: {exc}", repair="choose_output_folder", suggestion="Choose a writable output folder.")

        ffmpeg = manager.find_ffmpeg()
        if ffmpeg:
            try:
                version = self.command_first_line([ffmpeg, "-hide_banner", "-version"], timeout=6)
                self.add_health_check(checks, "ok", "FFmpeg", f"{ffmpeg} ({version})")
            except Exception as exc:
                self.add_health_check(checks, "warn", "FFmpeg", f"Found but version check failed: {ffmpeg} ({exc})")
        else:
            self.add_health_check(checks, "error", "FFmpeg", "Not found. Bundled FFmpeg or configured path is required.", repair="reset_ffmpeg_path", suggestion="Use the bundled FFmpeg runtime when available.")

        ffprobe = manager.find_ffprobe()
        if ffprobe:
            self.add_health_check(checks, "ok", "FFprobe", ffprobe)
        else:
            self.add_health_check(checks, "warn", "FFprobe", "Not found. Media/audio validation may be limited.", repair="reset_ffmpeg_path", suggestion="Restore the bundled FFmpeg/FFprobe path.")

        obs = manager.find_obs_exe()
        backend = str(config.get("capture_backend", "auto"))
        if obs:
            obs_root = manager.obs_root_dir(obs)
            missing = []
            for relative in (
                Path("obs-plugins") / "64bit" / "obs-websocket.dll",
                Path("obs-plugins") / "64bit" / "win-capture.dll",
                Path("bin") / "64bit" / "obs64.exe",
            ):
                if not (obs_root / relative).exists():
                    missing.append(str(relative))
            if missing:
                self.add_health_check(checks, "warn", "OBS runtime", f"{obs}; missing: {', '.join(missing)}")
            else:
                self.add_health_check(checks, "ok", "OBS runtime", obs)
        else:
            level = "error" if backend == "obs" else "warn"
            self.add_health_check(checks, level, "OBS runtime", "Not found. OBS backend will not start.", repair="reset_obs_path", suggestion="Use the bundled OBS runtime when available.")

        try:
            ffmpeg_limited = backend != "obs" and bool(ffmpeg)
            encoder = manager.resolve_video_encoder(ffmpeg_limited=ffmpeg_limited, log_selection=False)
            detail = f"Selected {video_encoder_label(encoder)} from setting {video_encoder_label(config.get('video_encoder', 'auto'))}."
            if encoder in HARDWARE_VIDEO_ENCODERS:
                self.add_health_check(checks, "ok", "Hardware encoder", detail)
            else:
                self.add_health_check(checks, "warn", "Hardware encoder", detail + " CPU fallback may reduce performance.", repair="auto_encoder", suggestion="Reset encoder selection to Auto and detect the GPU again.")
        except Exception as exc:
            self.add_health_check(checks, "warn", "Hardware encoder", f"Could not determine encoder: {exc}")

        try:
            recommended_mb = recommended_obs_replay_buffer_mb(
                config.get("clip_seconds", DEFAULT_CONFIG["clip_seconds"]),
                config.get("video_bitrate_mbps", DEFAULT_CONFIG["video_bitrate_mbps"]),
            )
            current_mb = int(config.get("obs_replay_buffer_mb", DEFAULT_CONFIG["obs_replay_buffer_mb"]) or 0)
            clip_seconds = int(config.get("clip_seconds", DEFAULT_CONFIG["clip_seconds"]) or 0)
            bitrate = int(config.get("video_bitrate_mbps", DEFAULT_CONFIG["video_bitrate_mbps"]) or 0)
            if bool(config.get("obs_replay_ram_auto", DEFAULT_CONFIG["obs_replay_ram_auto"])):
                level = "ok" if current_mb == recommended_mb else "warn"
                self.add_health_check(
                    checks,
                    level,
                    "OBS replay RAM",
                    f"Auto: {current_mb} MB for {clip_seconds}s @ {bitrate} Mbps; recommended {recommended_mb} MB.",
                    repair="sync_auto_replay_ram" if level == "warn" else "",
                    suggestion="Recalculate replay RAM from clip length and bitrate." if level == "warn" else "",
                )
            elif current_mb < recommended_mb:
                self.add_health_check(
                    checks,
                    "warn",
                    "OBS replay RAM",
                    f"Manual: {current_mb} MB is below recommended {recommended_mb} MB for {clip_seconds}s @ {bitrate} Mbps.",
                    repair="enable_auto_replay_ram",
                    suggestion="Enable automatic replay RAM allocation.",
                )
            else:
                self.add_health_check(
                    checks,
                    "ok",
                    "OBS replay RAM",
                    f"Manual: {current_mb} MB covers recommended {recommended_mb} MB.",
                )
        except Exception as exc:
            self.add_health_check(checks, "warn", "OBS replay RAM", f"Could not validate RAM limit: {exc}")

        if state.get("replay_running"):
            self.add_health_check(checks, "ok", "Replay buffer", "Running.")
            if backend == "obs":
                try:
                    client = manager.obs_client_connect(timeout=3)
                    try:
                        status = client.request("GetReplayBufferStatus")
                        if status.get("outputActive"):
                            self.add_health_check(checks, "ok", "OBS replay status", "OBS reports replay buffer active.")
                        else:
                            self.add_health_check(checks, "error", "OBS replay status", "ShadowClip thinks replay is running, but OBS reports inactive.", repair="restart_replay", suggestion="Restart Instant Replay and reconnect OBS.")
                    finally:
                        client.close()
                except Exception as exc:
                    self.add_health_check(checks, "warn", "OBS replay status", f"Could not query OBS websocket: {exc}")
        else:
            self.add_health_check(checks, "warn", "Replay buffer", "Not running. Start replay before relying on clip hotkeys.", repair="start_replay", suggestion="Start Instant Replay now.")

        if state.get("recording_running"):
            self.add_health_check(checks, "ok", "Recording", "Recording is currently running.")
        else:
            self.add_health_check(checks, "ok", "Recording", "Idle.")

        try:
            dshow_devices, _raw = manager.scan_audio_devices() if ffmpeg else ([], "")
        except Exception:
            dshow_devices = []
        wasapi_loopbacks = manager.scan_wasapi_loopbacks()
        wasapi_mics = manager.scan_soundcard_mics()
        if dshow_devices or wasapi_loopbacks or wasapi_mics:
            self.add_health_check(
                checks,
                "ok",
                "Audio devices",
                f"DirectShow: {len(dshow_devices)}, WASAPI mics: {len(wasapi_mics)}, WASAPI loopbacks: {len(wasapi_loopbacks)}.",
            )
        else:
            self.add_health_check(checks, "warn", "Audio devices", "No audio devices detected by DirectShow/WASAPI scan.", repair="scan_audio", suggestion="Scan Windows audio devices again.")

        if bool(config.get("mic_enabled")):
            if sc is None or np is None:
                self.add_health_check(checks, "error", "Microphone", "Mic is enabled, but the WASAPI audio runtime is unavailable.")
            elif str(config.get("mic_device", "")).strip():
                self.add_health_check(checks, "ok", "Microphone", str(config.get("mic_device", "")).strip())
            else:
                self.add_health_check(checks, "error", "Microphone", "Mic is enabled, but no mic device is selected.", repair="scan_microphone", suggestion="Scan and select the preferred microphone.")
        else:
            self.add_health_check(checks, "warn", "Microphone", "Disabled.")

        if bool(config.get("desktop_audio_enabled")):
            backend_audio = str(config.get("desktop_audio_backend", "wasapi"))
            device = str(config.get("desktop_audio_device", "")).strip()
            if backend_audio == "wasapi" and sc is None:
                self.add_health_check(checks, "error", "Desktop audio", "Desktop audio is enabled, but the WASAPI audio runtime is unavailable.")
            elif device:
                self.add_health_check(checks, "ok", "Desktop audio", f"{backend_audio}: {device}")
            else:
                self.add_health_check(checks, "error", "Desktop audio", "Desktop audio is enabled, but no loopback/device is selected.", repair="scan_desktop_audio", suggestion="Scan and select the active Windows playback device.")
        else:
            self.add_health_check(checks, "warn", "Desktop audio", "Disabled.")

        mode = str(config.get("capture_mode", "desktop_all"))
        monitors = snapshot.get("monitors") or []
        if mode == "monitor":
            index = int(config.get("monitor_index", 0) or 0)
            if 0 <= index < len(monitors):
                monitor = monitors[index]
                self.add_health_check(
                    checks,
                    "ok",
                    "Capture source",
                    f"Monitor {index + 1}: {monitor.get('width')}x{monitor.get('height')} @ {monitor.get('left')},{monitor.get('top')}.",
                )
            else:
                self.add_health_check(checks, "error", "Capture source", f"Selected monitor index {index} is not available.", repair="select_primary_monitor", suggestion="Select the current Windows primary monitor.")
        elif mode == "window":
            title = str(config.get("window_title", "")).strip()
            if title:
                self.add_health_check(checks, "ok", "Capture source", f"Window/Game title: {title}")
            else:
                self.add_health_check(checks, "warn", "Capture source", "Window mode is selected, but no title is selected.", repair="select_primary_monitor", suggestion="Switch to reliable single-monitor OBS capture.")
        else:
            self.add_health_check(checks, "ok", "Capture source", "All screens.")

        return checks

    def health_check_summary(self, checks):
        return {
            "ok": sum(1 for check in checks if check.get("level") == "ok"),
            "warn": sum(1 for check in checks if check.get("level") == "warn"),
            "error": sum(1 for check in checks if check.get("level") == "error"),
        }

    def format_health_check_results(self, checks):
        summary = self.health_check_summary(checks)
        lines = [
            f"{APP_NAME} setup health check",
            f"Version: {APP_VERSION}",
            f"OK: {summary['ok']}   WARN: {summary['warn']}   ERROR: {summary['error']}",
            "",
        ]
        for check in checks:
            level = str(check.get("level", "info")).upper()
            lines.append(f"[{level}] {check.get('name', 'Check')}: {check.get('detail', '')}")
        return "\n".join(lines)

    def run_health_check(self):
        if self.health_check_running:
            self.threadsafe_log("Setup health check already running.")
            return
        snapshot = self.diagnostic_snapshot()
        self.health_check_running = True
        self.threadsafe_log("Running setup health check...")
        thread = threading.Thread(target=self.health_check_worker, args=(snapshot,), daemon=True)
        thread.start()

    def health_check_worker(self, snapshot):
        try:
            checks = self.build_health_checks(snapshot)
            self.root.after(0, lambda result=checks: self.show_health_check_results(result))
        except Exception as exc:
            self.root.after(0, lambda error=exc: self.finish_health_check_error(error))

    def show_health_check_results(self, checks):
        self.health_check_running = False
        summary = self.health_check_summary(checks)
        self.threadsafe_log(f"Setup health check finished: {summary['ok']} OK, {summary['warn']} warning(s), {summary['error']} error(s).")
        self.show_health_check_results_window(checks)

    def close_health_check_results(self):
        window = self.health_check_results_window
        self.health_check_results_window = None
        if window and window.winfo_exists():
            window.destroy()

    def health_repair_label(self, repair):
        return {
            "sync_auto_bitrate": "Recalculate",
            "enable_auto_bitrate": "Enable Auto",
            "choose_output_folder": "Choose Folder",
            "reset_ffmpeg_path": "Use Bundled",
            "reset_obs_path": "Use Bundled",
            "auto_encoder": "Detect Again",
            "sync_auto_replay_ram": "Recalculate",
            "enable_auto_replay_ram": "Enable Auto",
            "restart_replay": "Restart Replay",
            "start_replay": "Start Replay",
            "scan_audio": "Scan Audio",
            "scan_microphone": "Find Microphone",
            "scan_desktop_audio": "Find Output",
            "select_primary_monitor": "Use Primary",
        }.get(str(repair or ""), "Fix")

    def apply_health_repair(self, repair):
        repair = str(repair or "")
        if not repair:
            return
        self.close_health_check_results()
        rerun_delay = 700
        save_needed = True
        try:
            if repair == "sync_auto_bitrate":
                self.vars["auto_video_bitrate"].set(True)
                self.sync_auto_video_bitrate(force=True)
            elif repair == "enable_auto_bitrate":
                self.vars["auto_video_bitrate"].set(True)
                self.sync_auto_video_bitrate(force=True)
            elif repair == "sync_auto_replay_ram":
                self.vars["obs_replay_ram_auto"].set(True)
                self.sync_auto_obs_replay_buffer(force=True)
            elif repair == "enable_auto_replay_ram":
                self.vars["obs_replay_ram_auto"].set(True)
                self.sync_auto_obs_replay_buffer(force=True)
            elif repair == "auto_encoder":
                self.vars["video_encoder"].set("auto")
                self.manager.encoder_cache = None
                self.manager.encoder_log_signature = None
            elif repair == "reset_ffmpeg_path":
                self.vars["ffmpeg_path"].set("")
            elif repair == "reset_obs_path":
                self.vars["obs_path"].set("")
                self.vars["capture_backend"].set("obs")
            elif repair == "choose_output_folder":
                save_needed = False
                rerun_delay = 0
                self.health_repair_pending_output = True
                self.browse_output()
            elif repair in {"scan_audio", "scan_microphone", "scan_desktop_audio"}:
                self.scan_audio()
                if repair == "scan_microphone" and self.vars["mic_device"].get().strip():
                    self.vars["mic_enabled"].set(True)
                if repair == "scan_desktop_audio" and self.vars["desktop_audio_device"].get().strip():
                    self.vars["desktop_audio_enabled"].set(True)
                    self.vars["desktop_audio_backend"].set("wasapi")
            elif repair == "select_primary_monitor":
                self.refresh_monitors()
                primary = next((monitor for monitor in self.monitors if monitor.get("primary")), self.monitors[0] if self.monitors else None)
                if not primary:
                    raise RuntimeError("Windows did not report an available monitor.")
                self.vars["capture_mode"].set("monitor")
                self.vars["monitor_index"].set(int(primary.get("index", 0)))
                self.vars["capture_backend"].set("obs")
                self.refresh_monitors()
            elif repair == "start_replay":
                if self.save_settings() is False:
                    return
                save_needed = False
                if not self.replay_running():
                    self.toggle_replay()
                rerun_delay = 1800
            elif repair == "restart_replay":
                if self.save_settings() is False:
                    return
                save_needed = False
                if self.replay_running():
                    self.manager.stop_replay()
                self.manager.start_replay()
                self.update_tray_status()
                rerun_delay = 1800
            else:
                raise RuntimeError(f"Unknown repair action: {repair}")

            if save_needed and self.save_settings() is False:
                return
            self.threadsafe_log(f"One-click repair applied: {repair}.")
            self.show_event_toast("Repair applied", "ShadowClip updated the affected setting.", "check")
            if rerun_delay:
                self.root.after(rerun_delay, self.run_health_check)
        except Exception as exc:
            self.threadsafe_log(f"One-click repair failed ({repair}): {exc}")
            messagebox.showerror(APP_NAME, f"The repair could not be completed.\n\n{exc}", parent=self.root)

    def show_health_check_results_window(self, checks):
        self.close_health_check_results()
        colors = self.ui_colors
        summary = self.health_check_summary(checks)
        if summary["error"]:
            accent = "#ff6b6b"
            title = "Setup needs attention"
        elif summary["warn"]:
            accent = "#f5b942"
            title = "Setup is usable with warnings"
        else:
            accent = colors["accent"]
            title = "Setup looks healthy"

        window = tk.Toplevel(self.root)
        self.health_check_results_window = window
        window.title(f"{APP_NAME} Setup Check")
        window.configure(bg=colors["bg"])
        window.geometry("900x720")
        window.minsize(800, 620)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self.close_health_check_results)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        header = tk.Frame(window, bg=colors["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 16))
        header.columnconfigure(1, weight=1)
        tk.Label(header, text="!" if summary["error"] else "✓", width=3, bg=accent, fg="#071007", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, rowspan=2, padx=(0, 14), ipady=6)
        tk.Label(header, text=title, bg=colors["bg"], fg=colors["text"], font=("Segoe UI", 20, "bold"), anchor="w").grid(row=0, column=1, sticky="ew")
        tk.Label(header, text=f"{summary['ok']} OK   {summary['warn']} warnings   {summary['error']} errors", bg=colors["bg"], fg=colors["muted"], font=("Segoe UI", 10), anchor="w").grid(row=1, column=1, sticky="ew", pady=(3, 0))

        host = tk.Frame(window, bg=colors["bg"])
        host.grid(row=1, column=0, sticky="nsew", padx=28)
        host.columnconfigure(0, weight=1)
        host.rowconfigure(0, weight=1)
        canvas = tk.Canvas(host, bg=colors["bg"], highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        canvas.configure(yscrollcommand=scrollbar.set)
        body = tk.Frame(canvas, bg=colors["bg"])
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")), add="+")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=max(1, event.width)), add="+")
        palette = {"ok": colors["accent"], "warn": "#f5b942", "error": "#ff6b6b"}
        for check in checks:
            panel = self.dashboard_panel(body)
            panel.pack(fill="x", pady=5)
            panel.columnconfigure(1, weight=1)
            level = str(check.get("level") or "warn")
            color = palette.get(level, colors["muted"])
            tk.Label(panel, text="●", bg=colors["panel"], fg=color, font=("Segoe UI", 13)).grid(row=0, column=0, rowspan=3, padx=(16, 12), pady=13)
            tk.Label(panel, text=check.get("name", "Check"), bg=colors["panel"], fg=colors["text"], font=("Segoe UI", 10, "bold"), anchor="w").grid(row=0, column=1, sticky="ew", pady=(12, 0))
            tk.Label(panel, text=check.get("detail", ""), bg=colors["panel"], fg=colors["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=610).grid(row=1, column=1, sticky="ew", pady=(2, 0))
            suggestion = str(check.get("suggestion") or "")
            if suggestion:
                tk.Label(panel, text=suggestion, bg=colors["panel"], fg=color, font=("Segoe UI", 8, "bold"), anchor="w", justify="left", wraplength=610).grid(row=2, column=1, sticky="ew", pady=(3, 12))
            else:
                tk.Frame(panel, bg=colors["panel"], height=10).grid(row=2, column=1, sticky="ew")
            repair = str(check.get("repair") or "")
            if repair:
                self.small_action_button(panel, self.health_repair_label(repair), lambda action=repair: self.apply_health_repair(action), accent=True, icon_key="settings").grid(row=0, column=2, rowspan=3, sticky="e", padx=16, pady=14)

        def scroll(event):
            canvas.yview_scroll((-1 if event.delta > 0 else 1) * 3, "units")
            return "break"

        def bind_scroll_tree():
            stack = [canvas, body]
            while stack:
                widget = stack.pop()
                widget.bind("<MouseWheel>", scroll, add="+")
                stack.extend(widget.winfo_children())

        self.root.after_idle(bind_scroll_tree)
        footer = tk.Frame(window, bg=colors["bg_soft"], height=76, highlightbackground=colors["border_soft"], highlightthickness=1)
        footer.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        footer.grid_propagate(False)
        footer.columnconfigure(0, weight=1)
        self.small_action_button(footer, "Export Beta Report", self.export_debug_report, icon_key="logs").grid(row=0, column=1, padx=7, pady=18)
        self.small_action_button(footer, "Run Again", lambda: (self.close_health_check_results(), self.run_health_check()), icon_key="replay").grid(row=0, column=2, padx=7, pady=18)
        self.small_action_button(footer, "Close", self.close_health_check_results, accent=True, icon_key="check").grid(row=0, column=3, padx=(7, 22), pady=18)
        window.lift()

    def finish_health_check_error(self, error):
        self.health_check_running = False
        self.threadsafe_log(f"Setup health check failed: {error}")
        messagebox.showerror(APP_NAME, f"Setup health check failed:\n{error}")

    def export_debug_report(self):
        if self.debug_report_running:
            self.threadsafe_log("Debug report export already running.")
            return
        snapshot = self.diagnostic_snapshot()
        self.debug_report_running = True
        self.threadsafe_log("Exporting debug report...")
        thread = threading.Thread(target=self.debug_report_worker, args=(snapshot,), daemon=True)
        thread.start()

    def debug_report_worker(self, snapshot):
        try:
            checks = self.build_health_checks(snapshot)
            report_path = self.write_debug_report_zip(snapshot, checks)
            self.root.after(0, lambda path=report_path: self.finish_debug_report(path))
        except Exception as exc:
            self.root.after(0, lambda error=exc: self.finish_debug_report_error(error))

    def write_debug_report_zip(self, snapshot, checks):
        support_id = self.beta_support_id()
        target = self.diagnostic_report_dir() / f"ShadowClip-beta-{support_id}-{datetime.now():%Y%m%d-%H%M%S}.zip"
        if target.exists():
            target = target.with_name(f"{target.stem}-{uuid.uuid4().hex[:6]}{target.suffix}")

        report_snapshot = self.privacy_safe_snapshot(snapshot)
        report_checks = self.privacy_safe_health_checks(checks)
        health_summary = self.health_check_summary(report_checks)
        self_test = (snapshot.get("state") or {}).get("capture_self_test_last_result") or {}
        beta_summary = {
            "support_id": support_id,
            "version": APP_VERSION,
            "created": datetime.now().isoformat(timespec="seconds"),
            "health": health_summary,
            "capture_self_test": {
                "summary": self_test.get("summary") or {},
                "metadata": self_test.get("metadata") or {},
            },
            "privacy": "User name, computer name, window titles, and personal directory roots are removed or replaced before export.",
        }

        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "README.txt",
                (
                    f"{APP_NAME} beta diagnostics\n"
                    f"Support ID: {support_id}\n"
                    f"Version: {APP_VERSION}\n"
                    f"Created: {datetime.now().isoformat(timespec='seconds')}\n\n"
                    "This report is intended for ShadowClip beta troubleshooting.\n"
                    "User name, computer name, window titles, and personal directory roots are redacted before export.\n"
                    "Review the ZIP before sharing it if you entered sensitive text into custom device or profile names.\n"
                ),
            )
            archive.writestr("support/beta_summary.json", json.dumps(beta_summary, indent=2, ensure_ascii=False))
            archive.writestr("diagnostics/health_check.txt", self.format_health_check_results(report_checks))
            archive.writestr("diagnostics/health_check.json", json.dumps(report_checks, indent=2, ensure_ascii=False))
            archive.writestr("state/snapshot_redacted.json", json.dumps(report_snapshot, indent=2, ensure_ascii=False))
            archive.writestr("config/shadowclip_config_redacted.json", json.dumps(report_snapshot.get("config", {}), indent=2, ensure_ascii=False))
            archive.writestr("logs/ui_log.txt", self.scrub_diagnostic_text(snapshot.get("ui_log", "") or ""))

            logs = []
            try:
                logs = sorted(
                    self.manager.logs_dir.glob("*.log"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )[:20]
            except Exception:
                logs = []
            for log_path in logs:
                try:
                    text = log_path.read_text(encoding="utf-8", errors="replace")
                    archive.writestr(f"logs/runtime/{log_path.name}", self.scrub_diagnostic_text(text))
                except OSError:
                    pass

        return target

    def finish_debug_report(self, report_path):
        self.debug_report_running = False
        support_id = self.beta_support_id()
        self.threadsafe_log(f"Beta diagnostics exported ({support_id}): {report_path}")
        messagebox.showinfo(APP_NAME, f"Beta diagnostics exported.\n\nSupport ID: {support_id}\n\n{report_path}")

    def finish_debug_report_error(self, error):
        self.debug_report_running = False
        self.threadsafe_log(f"Debug report export failed: {error}")
        messagebox.showerror(APP_NAME, f"Debug report export failed:\n{error}")

    def updates_dir(self):
        path = self.manager.runtime_dir / "updates"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def check_for_updates(self, silent=False):
        if self.update_check_running:
            if not silent:
                self.threadsafe_log("Update check already running.")
            return
        self.update_check_running = True
        if not silent:
            self.threadsafe_log("Checking for updates...")
        thread = threading.Thread(target=self.update_check_worker, args=(silent,), daemon=True)
        thread.start()

    def update_check_worker(self, silent):
        try:
            release = fetch_latest_release()
            tag_name = str(release.get("tag_name", "")).strip()
            latest_version = normalize_version_text(tag_name)
            if not latest_version:
                raise RuntimeError("Latest GitHub release has no tag name.")

            asset = choose_update_asset(release)
            if not asset:
                raise RuntimeError("Latest GitHub release has no ShadowClipSetup .exe asset.")

            info = {
                "release": release,
                "asset": asset,
                "latest_version": latest_version,
                "current_version": APP_VERSION,
                "download_url": asset.get("browser_download_url", ""),
                "asset_name": asset.get("name", "ShadowClipSetup.exe"),
                "asset_size": asset.get("size", 0),
                "sha256": parse_asset_sha256(asset),
            }

            if is_newer_version(latest_version, APP_VERSION):
                self.root.after(0, lambda data=info: self.prompt_update_available(data))
            elif not silent:
                self.root.after(0, lambda: messagebox.showinfo(APP_NAME, f"ShadowClip is up to date.\n\nCurrent version: {APP_VERSION}"))
                self.threadsafe_log(f"ShadowClip is up to date ({APP_VERSION}).")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                message = f"No GitHub release found yet for {UPDATE_REPO}."
            else:
                message = f"GitHub update check failed: HTTP {exc.code}"
            if not silent:
                self.root.after(0, lambda msg=message: messagebox.showwarning(APP_NAME, msg))
                self.threadsafe_log(message)
        except Exception as exc:
            message = f"Update check failed: {exc}"
            if not silent:
                self.root.after(0, lambda msg=message: messagebox.showwarning(APP_NAME, msg))
                self.threadsafe_log(message)
        finally:
            self.update_check_running = False

    def prompt_update_available(self, info):
        size_text = format_bytes(info.get("asset_size", 0))
        body = (
            f"A new ShadowClip update is available.\n\n"
            f"Current: {info['current_version']}\n"
            f"Latest: {info['latest_version']}\n"
            f"Download: {info['asset_name']} ({size_text})\n\n"
            "Download and install it now?"
        )
        self.threadsafe_log(f"Update available: {info['latest_version']} ({info['asset_name']}).")
        if messagebox.askyesno(APP_NAME, body):
            self.download_update(info)

    def download_update(self, info):
        if self.update_download_running:
            self.threadsafe_log("Update download already running.")
            return
        url = str(info.get("download_url", "")).strip()
        if not url:
            messagebox.showerror(APP_NAME, "The update asset has no download URL.")
            return
        self.update_download_running = True
        self.threadsafe_log(f"Downloading update: {info['asset_name']}")
        thread = threading.Thread(target=self.update_download_worker, args=(info,), daemon=True)
        thread.start()

    def update_download_worker(self, info):
        try:
            target = self.updates_dir() / str(info.get("asset_name") or "ShadowClipSetup.exe")
            temp_target = target.with_suffix(target.suffix + ".download")
            if temp_target.exists():
                temp_target.unlink()

            request = urllib.request.Request(
                info["download_url"],
                headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
            )
            with urllib.request.urlopen(request, timeout=30) as response, temp_target.open("wb") as handle:
                shutil.copyfileobj(response, handle, length=1024 * 1024)
            temp_target.replace(target)

            expected_sha256 = str(info.get("sha256", ""))
            if expected_sha256:
                actual_sha256 = sha256_file(target)
                if actual_sha256.casefold() != expected_sha256.casefold():
                    try:
                        target.unlink()
                    except OSError:
                        pass
                    raise RuntimeError("Downloaded installer failed SHA256 verification.")
                self.threadsafe_log("Update download verified with SHA256.")
            else:
                self.threadsafe_log("Update download has no GitHub SHA256 digest; install only if you trust this release.")

            self.root.after(0, lambda path=target, data=info: self.prompt_install_update(path, data))
        except Exception as exc:
            self.threadsafe_log(f"Update download failed: {exc}")
            self.root.after(0, lambda error=exc: messagebox.showerror(APP_NAME, f"Update download failed:\n{error}"))
        finally:
            self.update_download_running = False

    def prompt_install_update(self, installer_path, info):
        body = (
            f"Update downloaded:\n{installer_path}\n\n"
            "ShadowClip will stop capture, close, install the update, and relaunch after a short delay. Continue?"
        )
        self.threadsafe_log(f"Update downloaded: {installer_path}")
        if messagebox.askyesno(APP_NAME, body):
            self.install_update(installer_path)

    def install_update(self, installer_path):
        installer_path = Path(installer_path)
        if not installer_path.exists():
            messagebox.showerror(APP_NAME, f"Installer not found:\n{installer_path}")
            return
        launcher_path = self.updates_dir() / "RunShadowClipUpdate.cmd"
        installed_exe = APP_DIR / "ShadowClip.exe"
        launcher_text = (
            "@echo off\r\n"
            "setlocal EnableDelayedExpansion\r\n"
            "set \"PID=%~1\"\r\n"
            "set \"SETUP=%~2\"\r\n"
            "set \"APP=%~3\"\r\n"
            "set \"WAIT_COUNT=0\"\r\n"
            ":wait_shadowclip\r\n"
            "tasklist /FI \"PID eq %PID%\" | find \"%PID%\" >nul\r\n"
            "if not errorlevel 1 (\r\n"
            "  timeout /t 1 /nobreak >nul\r\n"
            "  set /a WAIT_COUNT+=1\r\n"
            "  if !WAIT_COUNT! LSS 60 goto wait_shadowclip\r\n"
            ")\r\n"
            "tasklist /FI \"PID eq %PID%\" | find \"%PID%\" >nul\r\n"
            "if not errorlevel 1 taskkill /PID %PID% /T /F >nul 2>nul\r\n"
            "timeout /t 3 /nobreak >nul\r\n"
            "start \"\" /wait \"%SETUP%\" /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS\r\n"
            "timeout /t 8 /nobreak >nul\r\n"
            "if exist \"%APP%\" start \"\" \"%APP%\"\r\n"
            "endlocal\r\n"
        )
        launcher_path.write_text(launcher_text, encoding="ascii")

        self.threadsafe_log("Preparing update: stopping capture before installer starts.")
        self.is_quitting = True
        try:
            self.save_settings()
        except Exception:
            pass
        try:
            self.manager.stop_all()
        except Exception as exc:
            self.threadsafe_log(f"Update stop warning: {exc}")
        self.hotkeys.stop()
        if self.tray:
            self.tray.stop()
        self.destroy_event_toast()
        self.hide_recording_indicator()
        self.threadsafe_log("Starting update installer and closing ShadowClip.")
        subprocess.Popen(
            ["cmd.exe", "/c", str(launcher_path), str(os.getpid()), str(installer_path), str(installed_exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        self.root.after(1200, self.root.destroy)

    def open_last_clip(self):
        self.collect_config()
        clip = self.manager.latest_clip_path()
        if not clip:
            self.threadsafe_log("No saved clip found yet.")
            return
        self.play_clip_path(clip)

    def show_last_clip(self):
        self.collect_config()
        clip = self.manager.latest_clip_path()
        if not clip:
            self.threadsafe_log("No saved clip found yet.")
            return
        self.reveal_clip_path(clip)

    def play_clip_path(self, clip):
        clip = Path(clip)
        if not clip.exists():
            self.threadsafe_log(f"Clip not found: {clip}")
            return
        os.startfile(str(clip))
        self.threadsafe_log(f"Opened clip: {clip}")

    def reveal_clip_path(self, clip):
        clip = Path(clip).resolve()
        if not clip.exists():
            self.threadsafe_log(f"Clip not found: {clip}")
            return
        try:
            reveal_file_in_explorer(clip)
            self.threadsafe_log(f"Showing clip: {clip}")
        except Exception as exc:
            try:
                os.startfile(str(clip.parent))
                self.threadsafe_log(f"Opened clip folder after Explorer selection failed: {clip.parent} ({exc})")
            except OSError as fallback_exc:
                self.threadsafe_log(f"Could not show clip in Explorer: {fallback_exc}")

    def auto_start_replay(self):
        if self.replay_running():
            return
        self.threadsafe_log("Auto-starting replay buffer.")
        self.toggle_replay()

    def toggle_replay(self):
        self.prepare_capture_action("toggle replay")
        try:
            self.manager.toggle_replay()
            self.update_tray_status()
        except Exception as exc:
            self.threadsafe_log(f"Replay error: {exc}")

    def save_clip(self):
        self.prepare_capture_action("save clip")
        self.manager.save_clip_async()

    def toggle_recording(self):
        self.prepare_capture_action("toggle recording")
        try:
            self.manager.toggle_recording()
            self.update_tray_status()
        except Exception as exc:
            self.threadsafe_log(f"Recording error: {exc}")

    def stop_all(self):
        self.manager.stop_all()
        self.update_tray_status()

    def dispatch_hotkey(self, action):
        self.root.after(0, lambda: self.handle_hotkey(action))

    def handle_hotkey(self, action):
        if action == "save_clip":
            self.save_clip()
        elif action == "toggle_replay":
            self.toggle_replay()
        elif action == "toggle_recording":
            self.toggle_recording()
        elif action == "toggle_overlay":
            self.toggle_overlay()
        elif action == "make_borderless":
            self.make_foreground_borderless()

    def dispatch_tray_action(self, action):
        self.root.after(0, lambda: self.handle_tray_action(action))

    def handle_tray_action(self, action):
        if action == "show_window":
            self.show_window()
        elif action == "hide_window":
            self.hide_window()
        elif action == "toggle_replay":
            self.toggle_replay()
        elif action == "save_clip":
            self.save_clip()
        elif action == "toggle_recording":
            self.toggle_recording()
        elif action == "stop_all":
            self.stop_all()
        elif action == "make_borderless":
            self.make_foreground_borderless()
        elif action == "open_output":
            self.open_output()
        elif action == "open_last_clip":
            self.open_last_clip()
        elif action == "show_last_clip":
            self.show_last_clip()
        elif action == "exit":
            self.exit_app()

    def toggle_overlay(self):
        if self.overlay_visible:
            self.hide_overlay()
        else:
            self.show_overlay()

    def overlay_bounds_from_monitor(self, hmonitor):
        if os.name != "nt" or not hmonitor:
            return None
        user32 = ctypes.windll.user32
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            return None
        rect = info.rcMonitor
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            return None
        return {
            "left": int(rect.left),
            "top": int(rect.top),
            "width": width,
            "height": height,
        }

    def install_noactivate_mouse_filter(self, window):
        if os.name != "nt" or not window or not window.winfo_exists():
            return
        try:
            window.update_idletasks()
            hwnd = wintypes.HWND(window.winfo_id())
            hwnd_key = int(hwnd.value or 0)
            if not hwnd_key or hwnd_key in self.noactivate_window_procs:
                return
            user32 = ctypes.windll.user32
            try:
                get_window_long = user32.GetWindowLongPtrW
                set_window_long = user32.SetWindowLongPtrW
            except AttributeError:
                get_window_long = user32.GetWindowLongW
                set_window_long = user32.SetWindowLongW
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_window_long.restype = ctypes.c_ssize_t
            user32.CallWindowProcW.argtypes = [
                ctypes.c_ssize_t,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.CallWindowProcW.restype = LRESULT
            old_proc = int(get_window_long(hwnd, GWLP_WNDPROC))

            def noactivate_proc(proc_hwnd, message, wparam, lparam):
                if message == WM_MOUSEACTIVATE:
                    return MA_NOACTIVATE
                return user32.CallWindowProcW(old_proc, proc_hwnd, message, wparam, lparam)

            callback = WNDPROC(noactivate_proc)
            set_window_long(hwnd, GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p).value)
            self.noactivate_window_procs[hwnd_key] = (old_proc, callback)
            window.bind(
                "<Destroy>",
                lambda event, key=hwnd_key: self.noactivate_window_procs.pop(key, None),
                add="+",
            )
        except Exception:
            pass

    def set_window_game_overlay_style(self, window, click_through=False):
        if os.name != "nt" or not window or not window.winfo_exists():
            return
        try:
            window.update_idletasks()
            self.install_noactivate_mouse_filter(window)
            hwnd = wintypes.HWND(window.winfo_id())
            user32 = ctypes.windll.user32
            try:
                get_window_long = user32.GetWindowLongPtrW
                set_window_long = user32.SetWindowLongPtrW
            except AttributeError:
                get_window_long = user32.GetWindowLongW
                set_window_long = user32.SetWindowLongW
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_window_long.restype = ctypes.c_ssize_t
            style = int(get_window_long(hwnd, GWL_EXSTYLE))
            style |= WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            if click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            set_window_long(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        except Exception:
            pass

    def show_window_game_overlay(self, window, click_through=False, allow_lift=True):
        if not window or not window.winfo_exists():
            return
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            return
        self.set_window_game_overlay_style(window, click_through=click_through)
        try:
            # Tk must leave the withdrawn state before native no-activate calls
            # can keep a newly-created toast or status icon visible.
            window.deiconify()
            window.update_idletasks()
        except tk.TclError:
            return
        if os.name == "nt":
            try:
                ctypes.windll.user32.ShowWindow(wintypes.HWND(window.winfo_id()), SW_SHOWNOACTIVATE)
            except Exception:
                try:
                    window.deiconify()
                except tk.TclError:
                    return
        else:
            try:
                window.deiconify()
            except tk.TclError:
                return
        self.set_window_game_overlay_style(window, click_through=click_through)
        if allow_lift:
            try:
                window.lift()
            except tk.TclError:
                pass

    def keep_game_overlay_visible(self, window, click_through=False, attempts=3, delay_ms=120, allow_lift=True):
        if not window or not window.winfo_exists():
            return
        self.show_window_game_overlay(window, click_through=click_through, allow_lift=allow_lift)
        if attempts <= 1:
            return
        self.root.after(
            delay_ms,
            lambda: self.keep_game_overlay_visible(
                window,
                click_through=click_through,
                attempts=attempts - 1,
                delay_ms=delay_ms,
                allow_lift=allow_lift,
            ),
        )

    def shadowclip_hwnds(self):
        hwnds = set()
        for widget in (self.root, self.overlay, self.event_toast, self.recording_indicator):
            if widget and widget.winfo_exists():
                try:
                    hwnds.add(int(widget.winfo_id()))
                except tk.TclError:
                    pass
        return hwnds

    def monitor_from_foreground_window(self):
        if os.name != "nt":
            return None
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        if int(hwnd) in self.shadowclip_hwnds():
            return None
        process_name = window_process_name(hwnd).casefold()
        if process_name in {APP_NAME.casefold(), Path(sys.executable).stem.casefold()}:
            return None
        monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        return monitor or None

    def monitor_from_cursor(self):
        if os.name != "nt":
            return None
        point = Point()
        user32 = ctypes.windll.user32
        user32.GetCursorPos.argtypes = [ctypes.POINTER(Point)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.MonitorFromPoint.argtypes = [Point, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
        return monitor or None

    def foreground_window_is_fullscreen(self):
        if os.name != "nt":
            return False
        try:
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
            user32.GetWindowRect.restype = wintypes.BOOL
            try:
                get_window_long = user32.GetWindowLongPtrW
            except AttributeError:
                get_window_long = user32.GetWindowLongW
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            hwnd = user32.GetForegroundWindow()
            if not hwnd or int(hwnd) in self.shadowclip_hwnds():
                return False
            process_name = window_process_name(hwnd).casefold()
            if process_name in {APP_NAME.casefold(), Path(sys.executable).stem.casefold()}:
                return False
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            bounds = self.overlay_bounds_from_monitor(monitor)
            if not bounds:
                return False
            rect = Rect()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return False
            left = int(rect.left)
            top = int(rect.top)
            right = int(rect.right)
            bottom = int(rect.bottom)
            tolerance = 4
            strict_fullscreen = (
                left <= bounds["left"] + tolerance
                and top <= bounds["top"] + tolerance
                and right >= bounds["left"] + bounds["width"] - tolerance
                and bottom >= bounds["top"] + bounds["height"] - tolerance
            )
            if strict_fullscreen:
                return True

            intersect_left = max(left, bounds["left"])
            intersect_top = max(top, bounds["top"])
            intersect_right = min(right, bounds["left"] + bounds["width"])
            intersect_bottom = min(bottom, bounds["top"] + bounds["height"])
            intersect_area = max(0, intersect_right - intersect_left) * max(0, intersect_bottom - intersect_top)
            monitor_area = max(1, bounds["width"] * bounds["height"])
            style = int(get_window_long(hwnd, GWL_STYLE))
            has_caption = bool(style & WS_CAPTION)
            return (intersect_area / monitor_area) >= 0.92 and not has_caption
        except Exception:
            return False

    def foreground_fullscreen_context(self):
        if os.name != "nt":
            return None
        try:
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
            user32.GetWindowRect.restype = wintypes.BOOL
            try:
                get_window_long = user32.GetWindowLongPtrW
            except AttributeError:
                get_window_long = user32.GetWindowLongW
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            hwnd = user32.GetForegroundWindow()
            if not hwnd or int(hwnd) in self.shadowclip_hwnds():
                return None
            process_name = window_process_name(hwnd)
            if process_name.casefold() in {APP_NAME.casefold(), Path(sys.executable).stem.casefold()}:
                return None
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            bounds = self.overlay_bounds_from_monitor(monitor)
            if not bounds:
                return None
            rect = Rect()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None

            left = int(rect.left)
            top = int(rect.top)
            right = int(rect.right)
            bottom = int(rect.bottom)
            tolerance = 4
            strict_fullscreen = (
                left <= bounds["left"] + tolerance
                and top <= bounds["top"] + tolerance
                and right >= bounds["left"] + bounds["width"] - tolerance
                and bottom >= bounds["top"] + bounds["height"] - tolerance
            )
            style = int(get_window_long(hwnd, GWL_STYLE))
            has_caption = bool(style & WS_CAPTION)
            intersect_left = max(left, bounds["left"])
            intersect_top = max(top, bounds["top"])
            intersect_right = min(right, bounds["left"] + bounds["width"])
            intersect_bottom = min(bottom, bounds["top"] + bounds["height"])
            intersect_area = max(0, intersect_right - intersect_left) * max(0, intersect_bottom - intersect_top)
            monitor_area = max(1, bounds["width"] * bounds["height"])
            near_fullscreen = (intersect_area / monitor_area) >= 0.92 and not has_caption
            if not (strict_fullscreen or near_fullscreen):
                return None

            title = get_window_text(hwnd)
            return {
                "hwnd": int(hwnd),
                "title": title,
                "process": process_name,
                "bounds": bounds,
                "signature": (
                    process_name.casefold(),
                    bounds["left"],
                    bounds["top"],
                    bounds["width"],
                    bounds["height"],
                ),
            }
        except Exception:
            return None

    def is_opengl_capture_risk_context(self, context):
        process_name = str(context.get("process", "")).casefold()
        title = str(context.get("title", "")).casefold()
        risky_processes = {
            "java",
            "javaw",
            "minecraft",
            "minecraft.windows",
            "minecraftlauncher",
        }
        if process_name in risky_processes:
            return True
        return "minecraft" in title

    def foreground_window_context(self):
        if os.name != "nt":
            return None
        try:
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            hwnd = user32.GetForegroundWindow()
            if not hwnd or int(hwnd) in self.shadowclip_hwnds():
                return None
            process_name = window_process_name(hwnd)
            if process_name.casefold() in {APP_NAME.casefold(), Path(sys.executable).stem.casefold()}:
                return None
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            bounds = self.overlay_bounds_from_monitor(monitor)
            if not bounds:
                return None
            return {
                "hwnd": int(hwnd),
                "title": get_window_text(hwnd),
                "process": process_name,
                "bounds": bounds,
            }
        except Exception:
            return None

    def make_foreground_borderless(self):
        context = self.foreground_window_context()
        if not context:
            self.threadsafe_log("Borderless helper skipped: no foreground game window found.")
            return
        if not self.is_opengl_capture_risk_context(context):
            label = context.get("title") or context.get("process") or "foreground window"
            self.threadsafe_log(f"Borderless helper skipped: {label} is not a Minecraft/Java window.")
            return

        label = context.get("title") or context.get("process") or "Minecraft"
        fullscreen_context = self.foreground_fullscreen_context()
        self.threadsafe_log(f"Minecraft borderless fix requested for {label}.")
        if fullscreen_context and fullscreen_context.get("hwnd") == context["hwnd"]:
            self.send_f11_to_window(context["hwnd"])
            self.threadsafe_log("Minecraft borderless fix: sent F11 to leave exclusive fullscreen.")
            self.root.after(1100, lambda ctx=context: self.apply_borderless_to_window(ctx))
        else:
            self.apply_borderless_to_window(context)

    def send_f11_to_window(self, hwnd):
        if os.name != "nt" or not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            target = wintypes.HWND(int(hwnd))
            user32.PostMessageW(target, WM_KEYDOWN, VK_F11, 0)
            self.root.after(80, lambda handle=int(hwnd): ctypes.windll.user32.PostMessageW(wintypes.HWND(handle), WM_KEYUP, VK_F11, 0))
        except Exception:
            pass

    def apply_borderless_to_window(self, context):
        if os.name != "nt" or not context:
            return
        hwnd_value = int(context.get("hwnd") or 0)
        if not hwnd_value:
            return
        hwnd = wintypes.HWND(hwnd_value)
        bounds = context.get("bounds") or self.current_overlay_bounds()
        label = context.get("title") or context.get("process") or "Minecraft"
        try:
            user32 = ctypes.windll.user32
            try:
                get_window_long = user32.GetWindowLongPtrW
                set_window_long = user32.SetWindowLongPtrW
            except AttributeError:
                get_window_long = user32.GetWindowLongW
                set_window_long = user32.SetWindowLongW
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_window_long.restype = ctypes.c_ssize_t

            style = int(get_window_long(hwnd, GWL_STYLE))
            style &= ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
            set_window_long(hwnd, GWL_STYLE, style)

            exstyle = int(get_window_long(hwnd, GWL_EXSTYLE))
            exstyle &= ~(WS_EX_DLGMODALFRAME | WS_EX_CLIENTEDGE | WS_EX_WINDOWEDGE)
            set_window_long(hwnd, GWL_EXSTYLE, exstyle)

            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetWindowPos(
                hwnd,
                HWND_TOP,
                int(bounds["left"]),
                int(bounds["top"]),
                int(bounds["width"]),
                int(bounds["height"]),
                SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOOWNERZORDER,
            )
            self.threadsafe_log(f"Minecraft borderless fix applied: {label}.")
            self.restart_replay_after_borderless_fix(label)
        except Exception as exc:
            self.threadsafe_log(f"Minecraft borderless fix failed: {exc}")

    def restart_replay_after_borderless_fix(self, label):
        if not self.replay_running():
            self.threadsafe_log("Minecraft borderless fix: start replay after applying the fix to capture gameplay.")
            return
        thread = threading.Thread(
            target=self.restart_replay_after_borderless_fix_worker,
            args=(label,),
            daemon=True,
        )
        thread.start()

    def restart_replay_after_borderless_fix_worker(self, label):
        try:
            self.manager.restart_replay_capture(
                reason=f"Minecraft borderless fix applied ({label}); restarting capture on GDI.",
                backend_override="gdigrab" if self.config.get("capture_backend", "auto") == "auto" else None,
            )
            self.root.after(0, self.update_tray_status)
        except Exception as exc:
            self.threadsafe_log(f"Minecraft borderless replay restart failed: {exc}")

    def monitor_fullscreen_capture_context(self):
        if self.is_quitting:
            return
        try:
            context = self.foreground_fullscreen_context()
            if context:
                self.manager.remember_capture_context(context)
                if self.is_opengl_capture_risk_context(context):
                    self.handle_opengl_fullscreen_capture_context(context)
                else:
                    self.fullscreen_capture_signature = None
            else:
                self.fullscreen_capture_signature = None
        finally:
            if not self.is_quitting and self.root.winfo_exists():
                self.root.after(2000, self.monitor_fullscreen_capture_context)

    def handle_opengl_fullscreen_capture_context(self, context):
        signature = context["signature"]
        label = context.get("title") or context.get("process") or "fullscreen game"
        warning_key = f"risk:{signature}"
        if warning_key not in self.fullscreen_capture_warning_keys:
            self.fullscreen_capture_warning_keys.add(warning_key)
            self.threadsafe_log(
                f"Minecraft/OpenGL fullscreen detected ({label}). "
                "Exclusive fullscreen may hide ShadowClip HUD/toasts and can freeze desktop capture during display-mode switches."
            )

        if self.recording_running():
            recording_key = f"recording:{signature}"
            if recording_key not in self.fullscreen_capture_warning_keys:
                self.fullscreen_capture_warning_keys.add(recording_key)
                self.threadsafe_log(
                    "Manual recording is active while Minecraft/OpenGL fullscreen is foreground. "
                    "If the file freezes on the loading screen, start the recording after the world has loaded or use borderless/windowed fullscreen."
                )

        self.fullscreen_capture_signature = signature
        if not self.replay_running():
            return
        if getattr(self.manager, "replay_active_backend", None) == "obs":
            obs_key = f"obs:{signature}"
            if obs_key not in self.fullscreen_capture_warning_keys:
                self.fullscreen_capture_warning_keys.add(obs_key)
                self.threadsafe_log("OBS backend active; skipping FFmpeg-style Minecraft/OpenGL replay restart.")
            return
        now = time.time()
        if self.fullscreen_capture_pending_signature == signature:
            return
        if self.fullscreen_capture_last_restart_signature == signature and now - self.fullscreen_capture_last_restart_at < 60:
            return
        if now - self.fullscreen_capture_last_restart_at < 12:
            return

        if self.fullscreen_capture_restart_after_id:
            try:
                self.root.after_cancel(self.fullscreen_capture_restart_after_id)
            except tk.TclError:
                pass
        self.fullscreen_capture_pending_signature = signature
        self.threadsafe_log(f"Minecraft/OpenGL fullscreen capture will be re-initialized after the display settles: {label}")
        self.fullscreen_capture_restart_after_id = self.root.after(
            4500,
            lambda sig=signature, name=label: self.restart_replay_after_fullscreen_settled(sig, name),
        )

    def restart_replay_after_fullscreen_settled(self, signature, label):
        self.fullscreen_capture_restart_after_id = None
        self.fullscreen_capture_pending_signature = None
        if self.is_quitting or not self.replay_running():
            return
        context = self.foreground_fullscreen_context()
        if not context or context.get("signature") != signature or not self.is_opengl_capture_risk_context(context):
            return
        self.fullscreen_capture_last_restart_at = time.time()
        self.fullscreen_capture_last_restart_signature = signature
        thread = threading.Thread(
            target=self.restart_replay_for_fullscreen_game,
            args=(label,),
            daemon=True,
        )
        thread.start()

    def restart_replay_for_fullscreen_game(self, label):
        try:
            backend_override = "gdigrab" if self.config.get("capture_backend", "auto") == "auto" else None
            self.manager.restart_replay_capture(
                reason=(
                    f"Minecraft/OpenGL fullscreen settled ({label}); "
                    "restarting capture to avoid a stale loading-screen frame."
                ),
                backend_override=backend_override,
            )
            self.root.after(0, self.update_tray_status)
        except Exception as exc:
            self.threadsafe_log(f"Minecraft/OpenGL replay restart failed: {exc}")

    def fullscreen_safe_hud_enabled(self):
        try:
            return bool(self.vars["fullscreen_safe_hud"].get())
        except tk.TclError:
            return True

    def use_fullscreen_safe_hud(self):
        return self.fullscreen_safe_hud_enabled() and self.foreground_window_is_fullscreen()

    def current_overlay_bounds(self):
        bounds = {
            "left": 0,
            "top": 0,
            "width": self.root.winfo_screenwidth(),
            "height": self.root.winfo_screenheight(),
        }
        if os.name == "nt":
            try:
                monitor = self.monitor_from_foreground_window() or self.monitor_from_cursor()
                monitor_bounds = self.overlay_bounds_from_monitor(monitor)
                if monitor_bounds:
                    bounds = monitor_bounds
            except Exception:
                pass
        bounds["width"] = max(960, bounds["width"])
        bounds["height"] = max(540, bounds["height"])
        return bounds

    def overlay_geometry_from_bounds(self, bounds):
        return f"{bounds['width']}x{bounds['height']}{bounds['left']:+d}{bounds['top']:+d}"

    def reset_overlay_responsive_panels(self):
        for attr in ("overlay_settings", "overlay_gallery"):
            widget = getattr(self, attr, None)
            if widget and widget.winfo_exists():
                try:
                    widget.destroy()
                except tk.TclError:
                    pass
            setattr(self, attr, None)
        self.overlay_gallery_list = None
        self.overlay_gallery_canvas = None
        self.overlay_gallery_count_label = None

    def resize_overlay_to_current_screen(self, reset_responsive=False, force=False):
        if not self.overlay or not self.overlay.winfo_exists():
            return False
        bounds = self.current_overlay_bounds()
        changed = force or bounds != self.overlay_bounds
        if changed:
            self.overlay.geometry(self.overlay_geometry_from_bounds(bounds))
            self.overlay_bounds = bounds
            if reset_responsive:
                self.reset_overlay_responsive_panels()
        return changed

    def overlay_screen_size(self):
        bounds = self.overlay_bounds or self.current_overlay_bounds()
        return bounds["width"], bounds["height"]

    def show_overlay(self):
        if self.overlay and self.overlay.winfo_exists():
            mode = self.overlay_mode
            self.overlay_click_through = self.use_fullscreen_safe_hud()
            if self.overlay_click_through:
                mode = "home"
                self.overlay_mode = "home"
            self.resize_overlay_to_current_screen(reset_responsive=True)
            self.update_overlay_state()
            if not self.overlay_click_through:
                self.overlay.deiconify()
            if mode == "settings":
                self.show_overlay_settings()
            elif mode == "gallery":
                self.show_overlay_gallery()
            else:
                self.show_overlay_home()
            self.show_window_game_overlay(
                self.overlay,
                click_through=self.overlay_click_through,
                allow_lift=not self.overlay_click_through,
            )
            self.overlay_visible = True
            return

        overlay = tk.Toplevel(self.root)
        overlay.withdraw()
        self.overlay = overlay
        self.overlay_click_through = self.use_fullscreen_safe_hud()
        self.overlay_buttons = {}
        overlay.title(f"{APP_NAME} Overlay")
        overlay.configure(bg="#050605")
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        try:
            overlay.attributes("-alpha", 0.93)
        except tk.TclError:
            pass
        self.resize_overlay_to_current_screen(force=True)
        overlay.bind("<Escape>", lambda event: self.hide_overlay())
        overlay.protocol("WM_DELETE_WINDOW", self.hide_overlay)

        topbar = tk.Frame(overlay, bg="#050605")
        topbar.place(x=0, y=0, relwidth=1, height=58)
        tk.Label(
            topbar,
            text="ShadowClip",
            bg="#050605",
            fg="#f4f4f4",
            font=("Segoe UI", 16, "bold"),
        ).place(x=24, rely=0.5, anchor="w")

        corner = tk.Frame(topbar, bg="#050605")
        corner.place(relx=1.0, y=12, x=-18, anchor="ne")
        self.overlay_toggle_label = tk.Label(
            corner,
            text=self.hotkey_label("toggle_overlay").replace("+", " + "),
            bg="#050605",
            fg="#8fd14f",
            font=("Segoe UI", 10),
        )
        self.overlay_toggle_label.grid(row=0, column=0, sticky="e", padx=(0, 12))
        close_button = tk.Button(
            corner,
            text="X",
            command=self.hide_overlay,
            bg="#161916",
            fg="#f4f4f4",
            activebackground="#252a25",
            activeforeground="#ffffff",
            relief="flat",
            width=4,
            cursor="hand2",
        )
        close_button.grid(row=0, column=1, sticky="e")
        self.bind_button_hover(close_button, hover_bg="#252a25", hover_fg="#ffffff")

        self.overlay_home = tk.Frame(overlay, bg="#050605")
        self.overlay_home.place(relx=0.5, rely=0.14, anchor="n")

        tiles = tk.Frame(self.overlay_home, bg="#050605")
        tiles.grid(row=0, column=0, columnspan=4)
        self.add_overlay_tile(tiles, "replay", overlay_text("replay", "Instant Replay"), "toggle_replay", 0, 0)
        self.add_overlay_tile(tiles, "clip", overlay_text("clip", "Save Clip"), "save_clip", 0, 1)
        self.add_overlay_tile(tiles, "record", overlay_text("record", "Record"), "toggle_recording", 0, 2)
        self.add_overlay_tile(tiles, "gallery", overlay_text("gallery", "Gallery"), "open_gallery", 0, 3)

        quick = tk.Frame(self.overlay_home, bg="#050605")
        quick.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(18, 0))
        self.add_overlay_quick_button(quick, "mic", ui_text("mic", "Mic"), "toggle_mic", 0)
        self.add_overlay_quick_button(quick, "desktop", ui_text("desktop", "Desktop Audio"), "toggle_desktop_audio", 1)
        self.add_overlay_quick_button(quick, "settings", ui_text("settings", "Settings"), "show_settings", 2)

        hint = tk.Label(
            self.overlay_home,
            text=ui_text("hotkey", f"{self.hotkey_label('save_clip')} saves a clip"),
            bg="#101210",
            fg="#d7d7d7",
            anchor="w",
            padx=12,
            pady=6,
            font=("Segoe UI", 9),
        )
        hint.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        self.overlay_hint_label = hint

        self.overlay_mode = "home"
        self.update_overlay_state()
        self.show_window_game_overlay(
            overlay,
            click_through=self.overlay_click_through,
            allow_lift=not self.overlay_click_through,
        )
        self.overlay_visible = True

    def show_overlay_home(self):
        if not self.overlay or not self.overlay.winfo_exists():
            return
        self.resize_overlay_to_current_screen(reset_responsive=True)
        if self.overlay_settings:
            self.overlay_settings.place_forget()
        if self.overlay_gallery:
            self.overlay_gallery.place_forget()
        if self.overlay_home:
            self.overlay_home.place(relx=0.5, rely=0.14, anchor="n")
        self.overlay_mode = "home"
        self.update_overlay_state()

    def show_overlay_settings(self):
        if not self.overlay or not self.overlay.winfo_exists():
            self.show_overlay()
        self.resize_overlay_to_current_screen(reset_responsive=True)
        if self.overlay_home:
            self.overlay_home.place_forget()
        if self.overlay_gallery:
            self.overlay_gallery.place_forget()
        if not self.overlay_settings or not self.overlay_settings.winfo_exists():
            self.build_overlay_settings()
        self.overlay_settings.place(relx=0.5, rely=0.52, anchor="center")
        self.overlay_mode = "settings"
        self.update_overlay_state()

    def show_overlay_gallery(self):
        if not self.overlay or not self.overlay.winfo_exists():
            self.show_overlay()
        self.resize_overlay_to_current_screen(reset_responsive=True)
        if self.overlay_home:
            self.overlay_home.place_forget()
        if self.overlay_settings:
            self.overlay_settings.place_forget()
        if not self.overlay_gallery or not self.overlay_gallery.winfo_exists():
            self.build_overlay_gallery()
        self.refresh_overlay_gallery()
        self.overlay_gallery.place(relx=0.5, rely=0.52, anchor="center")
        self.overlay_mode = "gallery"
        self.update_overlay_state()

    def build_overlay_settings(self):
        overlay = self.overlay
        screen_w, screen_h = self.overlay_screen_size()
        shell_width = min(920, max(760, screen_w - 80))
        shell_height = min(620, max(390, screen_h - 110))

        shell = tk.Frame(overlay, bg="#070907")
        self.overlay_settings = shell

        sidebar = tk.Frame(shell, bg="#050605", width=150, height=shell_height)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 28))
        sidebar.grid_propagate(False)
        tk.Label(
            sidebar,
            text="Settings",
            bg="#050605",
            fg="#f4f4f4",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="n", pady=(18, 12))
        tk.Label(
            sidebar,
            text=ICONS.get("settings", "*"),
            bg="#050605",
            fg="#ffffff",
            font=("Segoe UI Symbol", 52, "bold"),
        ).pack(expand=True)

        panel = tk.Frame(shell, bg="#24292c", width=shell_width - 320, height=shell_height)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_propagate(False)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        tk.Frame(panel, bg="#76b900", height=4).grid(row=0, column=0, sticky="ew")

        canvas = tk.Canvas(panel, bg="#24292c", highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(panel, orient="vertical", command=canvas.yview, bg="#24292c", troughcolor="#1a1e20")
        content = tk.Frame(canvas, bg="#24292c")
        canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=1, column=0, sticky="nsew", padx=(26, 0), pady=22)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=22)

        def resize_content(event):
            canvas.itemconfigure(canvas_window, width=event.width)

        content.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", resize_content)
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))

        self.add_overlay_capture_section(content)
        self.add_overlay_video_section(content)
        self.add_overlay_audio_section(content)
        self.add_overlay_interface_section(content)
        self.add_overlay_storage_section(content)
        self.add_overlay_hotkeys_section(content)
        self.sync_overlay_setting_lists()
        self.bind_overlay_mousewheel(panel, canvas)

        actions = tk.Frame(shell, bg="#070907", width=150, height=shell_height)
        actions.grid(row=0, column=2, sticky="n", padx=(28, 0))
        actions.grid_propagate(False)
        save_button = tk.Button(
            actions,
            text=ui_text("settings", "Save"),
            command=self.save_overlay_settings,
            bg="#76b900",
            fg="#ffffff",
            activebackground="#8fd14f",
            activeforeground="#ffffff",
            relief="flat",
            height=3,
            font=("Segoe UI Symbol", 10, "bold"),
            cursor="hand2",
        )
        save_button.pack(fill="x", pady=(0, 12))
        self.bind_button_hover(save_button, hover_bg="#8fd14f", hover_fg="#ffffff")
        back_button = tk.Button(
            actions,
            text="Back",
            command=self.show_overlay_home,
            bg="#30363a",
            fg="#f4f4f4",
            activebackground="#41484d",
            activeforeground="#ffffff",
            relief="flat",
            height=3,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        back_button.pack(fill="x")
        self.bind_button_hover(back_button, hover_bg="#41484d", hover_fg="#ffffff")

    def build_overlay_gallery(self):
        overlay = self.overlay
        screen_w, screen_h = self.overlay_screen_size()
        shell_width = min(980, max(780, screen_w - 80))
        shell_height = min(620, max(390, screen_h - 110))

        shell = tk.Frame(overlay, bg="#050605")
        self.overlay_gallery = shell

        sidebar = tk.Frame(shell, bg="#050605", width=150, height=shell_height)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 28))
        sidebar.grid_propagate(False)
        tk.Label(
            sidebar,
            text="Gallery",
            bg="#050605",
            fg="#f4f4f4",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="n", pady=(18, 12))
        tk.Label(
            sidebar,
            text=ICONS.get("gallery", "*"),
            bg="#050605",
            fg="#ffffff",
            font=("Segoe UI Symbol", 52, "bold"),
        ).pack(expand=True)

        panel = tk.Frame(shell, bg="#202629", width=shell_width - 330, height=shell_height)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_propagate(False)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        tk.Frame(panel, bg="#76b900", height=4).grid(row=0, column=0, sticky="ew")
        header = tk.Frame(panel, bg="#202629")
        header.grid(row=1, column=0, sticky="ew", padx=26, pady=(20, 10))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text=ui_text("gallery", "Recent clips"),
            bg="#202629",
            fg="#f4f4f4",
            anchor="w",
            font=("Segoe UI Symbol", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.overlay_gallery_count_label = tk.Label(
            header,
            text="",
            bg="#202629",
            fg="#aeb6aa",
            anchor="e",
            font=("Segoe UI", 9),
        )
        self.overlay_gallery_count_label.grid(row=0, column=1, sticky="e")

        canvas = tk.Canvas(panel, bg="#202629", highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(panel, orient="vertical", command=canvas.yview, bg="#202629", troughcolor="#151a1c")
        content = tk.Frame(canvas, bg="#202629")
        canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=2, column=0, sticky="nsew", padx=(26, 0), pady=(0, 24))
        scrollbar.grid(row=2, column=1, sticky="ns", pady=(0, 24))
        content.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        self.overlay_gallery_canvas = canvas
        self.overlay_gallery_list = content
        self.bind_overlay_mousewheel(panel, canvas)

        actions = tk.Frame(shell, bg="#050605", width=150, height=shell_height)
        actions.grid(row=0, column=2, sticky="n", padx=(28, 0))
        actions.grid_propagate(False)
        play_last_button = tk.Button(
            actions,
            text=ui_text("play", "Play Last"),
            command=self.open_last_clip,
            bg="#76b900",
            fg="#ffffff",
            activebackground="#8fd14f",
            activeforeground="#ffffff",
            relief="flat",
            height=3,
            font=("Segoe UI Symbol", 10, "bold"),
            cursor="hand2",
        )
        play_last_button.pack(fill="x", pady=(0, 12))
        self.bind_button_hover(play_last_button, hover_bg="#8fd14f", hover_fg="#ffffff")
        folder_button = tk.Button(
            actions,
            text=ui_text("folder", "Open Folder"),
            command=self.open_output,
            bg="#30363a",
            fg="#f4f4f4",
            activebackground="#41484d",
            activeforeground="#ffffff",
            relief="flat",
            height=3,
            font=("Segoe UI Symbol", 10, "bold"),
            cursor="hand2",
        )
        folder_button.pack(fill="x", pady=(0, 12))
        self.bind_button_hover(folder_button, hover_bg="#41484d", hover_fg="#ffffff")
        refresh_button = tk.Button(
            actions,
            text=ui_text("replay", "Refresh"),
            command=self.refresh_overlay_gallery,
            bg="#30363a",
            fg="#f4f4f4",
            activebackground="#41484d",
            activeforeground="#ffffff",
            relief="flat",
            height=3,
            font=("Segoe UI Symbol", 10, "bold"),
            cursor="hand2",
        )
        refresh_button.pack(fill="x", pady=(0, 12))
        self.bind_button_hover(refresh_button, hover_bg="#41484d", hover_fg="#ffffff")
        back_button = tk.Button(
            actions,
            text="Back",
            command=self.show_overlay_home,
            bg="#30363a",
            fg="#f4f4f4",
            activebackground="#41484d",
            activeforeground="#ffffff",
            relief="flat",
            height=3,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        back_button.pack(fill="x")
        self.bind_button_hover(back_button, hover_bg="#41484d", hover_fg="#ffffff")

    def refresh_overlay_gallery(self):
        if not self.overlay_gallery_list or not self.overlay_gallery_list.winfo_exists():
            return
        for child in self.overlay_gallery_list.winfo_children():
            child.destroy()

        self.collect_config()
        clips = self.manager.recent_clip_paths(limit=self.gallery_limit())
        if hasattr(self, "overlay_gallery_count_label"):
            count_text = f"{len(clips)} clip" + ("" if len(clips) == 1 else "s")
            self.overlay_gallery_count_label.configure(text=count_text)
        if not clips:
            tk.Label(
                self.overlay_gallery_list,
                text="No clips saved yet.",
                bg="#202629",
                fg="#d7d7d7",
                anchor="w",
                font=("Segoe UI", 11, "bold"),
            ).pack(fill="x", pady=(12, 0))
            return

        for index, clip in enumerate(clips):
            self.add_gallery_clip_row(self.overlay_gallery_list, clip, index)
        if self.overlay_gallery_canvas:
            self.bind_overlay_mousewheel(self.overlay_gallery_list, self.overlay_gallery_canvas)

    def add_gallery_clip_row(self, parent, clip, index):
        try:
            stat = clip.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m. %H:%M")
            size = format_file_size(stat.st_size)
        except OSError:
            modified = ""
            size = ""
        bg = "#151b1d" if index % 2 == 0 else "#121719"
        row = tk.Frame(parent, bg=bg, highlightbackground="#2a3235", highlightthickness=1)
        row.pack(fill="x", pady=(0, 8))
        row.columnconfigure(1, weight=1)

        tk.Label(
            row,
            text=ICONS.get("clip", "*"),
            bg=bg,
            fg="#76b900",
            font=("Segoe UI Symbol", 18, "bold"),
            width=3,
        ).grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(10, 6), pady=10)
        tk.Label(
            row,
            text=clip.name,
            bg=bg,
            fg="#f4f4f4",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(10, 1))
        detail = f"{clip.parent.name}   {modified}   {size}".strip()
        tk.Label(
            row,
            text=detail,
            bg=bg,
            fg="#aeb6aa",
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(1, 10))

        play_button = tk.Button(
            row,
            text=ui_text("play", "Play"),
            command=lambda path=clip: self.play_clip_path(path),
            bg="#263127",
            fg="#f4f4f4",
            activebackground="#76b900",
            activeforeground="#ffffff",
            relief="flat",
            font=("Segoe UI Symbol", 8, "bold"),
            width=9,
            cursor="hand2",
        )
        play_button.grid(row=0, column=2, rowspan=2, padx=(0, 8), pady=12, sticky="ns")
        self.bind_button_hover(play_button, hover_bg="#76b900", hover_fg="#ffffff")
        show_button = tk.Button(
            row,
            text=ui_text("gallery", "Show"),
            command=lambda path=clip: self.reveal_clip_path(path),
            bg="#30363a",
            fg="#f4f4f4",
            activebackground="#41484d",
            activeforeground="#ffffff",
            relief="flat",
            font=("Segoe UI Symbol", 8, "bold"),
            width=9,
            cursor="hand2",
        )
        show_button.grid(row=0, column=3, rowspan=2, padx=(0, 10), pady=12, sticky="ns")
        self.bind_button_hover(show_button, hover_bg="#41484d", hover_fg="#ffffff")

    def bind_overlay_mousewheel(self, widget, canvas):
        def scroll(event):
            delta = getattr(event, "delta", 0)
            if delta:
                canvas.yview_scroll(int(-1 * (delta / 120)), "units")
            elif getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")
            return "break"

        def bind_tree(current):
            try:
                current.bind("<MouseWheel>", scroll)
                current.bind("<Button-4>", scroll)
                current.bind("<Button-5>", scroll)
            except tk.TclError:
                return
            for child in current.winfo_children():
                bind_tree(child)

        bind_tree(widget)

    def sync_overlay_setting_lists(self):
        pairs = [
            ("monitor_combo", "monitor_combo_overlay"),
            ("window_combo", "window_combo_overlay"),
            ("mic_combo", "mic_combo_overlay"),
            ("desktop_audio_combo", "desktop_audio_combo_overlay"),
        ]
        for source_name, target_name in pairs:
            source = getattr(self, source_name, None)
            target = getattr(self, target_name, None)
            if not source or not target:
                continue
            try:
                target["values"] = source["values"]
                if source_name == "monitor_combo":
                    selected = source.current()
                    if selected >= 0:
                        target.current(selected)
            except tk.TclError:
                pass

    def overlay_section(self, parent, title):
        frame = tk.Frame(parent, bg="#24292c")
        frame.pack(fill="x", pady=(0, 20))
        tk.Label(
            frame,
            text=title,
            bg="#24292c",
            fg="#f4f4f4",
            anchor="w",
            font=("Segoe UI Symbol", 10, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        for col in range(4):
            frame.columnconfigure(col, weight=1 if col in (1, 3) else 0)
        return frame

    def overlay_label(self, parent, text, row, column=0):
        tk.Label(
            parent,
            text=text,
            bg="#24292c",
            fg="#e8e8e8",
            anchor="w",
            font=("Segoe UI Symbol", 9, "bold"),
        ).grid(row=row, column=column, sticky="w", padx=(0, 12), pady=5)

    def overlay_hint(self, parent, text, row, column=0, columnspan=4):
        tk.Label(
            parent,
            text=text,
            bg="#24292c",
            fg="#aeb6aa",
            anchor="w",
            justify="left",
            wraplength=680,
            font=("Segoe UI", 8),
        ).grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=(0, 12), pady=(0, 8))

    def overlay_entry(self, parent, var, row, column=1, width=18, columnspan=1):
        entry = tk.Entry(
            parent,
            textvariable=var,
            bg="#1b2023",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            width=width,
            font=("Segoe UI", 9),
        )
        entry.grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=(0, 12), pady=5, ipady=5)
        return entry

    def overlay_button(self, parent, text, command, row, column, columnspan=1):
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg="#30363a",
            fg="#f4f4f4",
            activebackground="#41484d",
            activeforeground="#ffffff",
            relief="flat",
            font=("Segoe UI Symbol", 9, "bold"),
            cursor="hand2",
        )
        button.grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=(0, 12), pady=5, ipady=4)
        self.bind_button_hover(button, hover_bg="#41484d", hover_fg="#ffffff")
        return button

    def overlay_spinbox(self, parent, var, row, column, from_, to, increment=1, width=8):
        spinbox = tk.Spinbox(
            parent,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=var,
            bg="#1b2023",
            fg="#ffffff",
            buttonbackground="#30363a",
            insertbackground="#ffffff",
            relief="flat",
            width=width,
            font=("Segoe UI", 9),
        )
        spinbox.grid(row=row, column=column, sticky="w", padx=(0, 12), pady=5, ipady=4)
        return spinbox

    def overlay_combo(self, parent, var, values, row, column, width=14):
        combo = ttk.Combobox(parent, state="readonly", textvariable=var, values=values, width=width)
        combo.grid(row=row, column=column, sticky="ew", padx=(0, 12), pady=5)
        return combo

    def overlay_check(self, parent, text, var, row, column=0, columnspan=1):
        check = tk.Checkbutton(
            parent,
            text=text,
            variable=var,
            bg="#24292c",
            fg="#f4f4f4",
            activebackground="#24292c",
            activeforeground="#ffffff",
            selectcolor="#172111",
            font=("Segoe UI Symbol", 9, "bold"),
        )
        check.grid(row=row, column=column, columnspan=columnspan, sticky="w", padx=(0, 12), pady=5)
        return check

    def overlay_radio(self, parent, text, var, value, row):
        radio = tk.Radiobutton(
            parent,
            text=text,
            variable=var,
            value=value,
            bg="#24292c",
            fg="#f4f4f4",
            activebackground="#24292c",
            activeforeground="#ffffff",
            selectcolor="#172111",
            font=("Segoe UI Symbol", 9, "bold"),
        )
        radio.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        return radio

    def add_overlay_hotkeys_section(self, parent):
        section = self.overlay_section(parent, ui_text("hotkey", "Keyboard shortcuts"))
        for index, (action, label) in enumerate(HOTKEY_ACTIONS, start=1):
            entry = self.overlay_entry(section, self.hotkey_vars[action], index, 0, width=18)
            entry.bind("<KeyPress>", lambda event, hotkey_action=action: self.capture_hotkey(event, hotkey_action))
            tk.Label(
                section,
                text=label,
                bg="#24292c",
                fg="#d7d7d7",
                anchor="w",
                font=("Segoe UI", 9),
            ).grid(row=index, column=1, columnspan=3, sticky="w", padx=(0, 12), pady=5)

    def capture_hotkey(self, event, action):
        hotkey = hotkey_from_event(event)
        if hotkey:
            self.hotkey_vars[action].set(hotkey)
        return "break"

    def add_overlay_capture_section(self, parent):
        section = self.overlay_section(parent, ui_text("source", "Capture source"))
        self.overlay_radio(section, ui_text("monitor", "All screens"), self.vars["capture_mode"], "desktop_all", 1)
        self.overlay_radio(section, ui_text("monitor", "One monitor"), self.vars["capture_mode"], "monitor", 2)
        self.monitor_combo_overlay = ttk.Combobox(section, state="readonly")
        self.monitor_combo_overlay.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=5)
        self.monitor_combo_overlay.bind("<<ComboboxSelected>>", self.on_monitor_selected)
        self.overlay_radio(section, ui_text("window", "Window/Game title"), self.vars["capture_mode"], "window", 3)
        self.window_combo_overlay = ttk.Combobox(section, textvariable=self.vars["window_title"])
        self.window_combo_overlay.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=5)
        self.overlay_button(section, ui_text("replay", "Refresh"), self.refresh_windows, 3, 3)
        self.overlay_label(section, ui_text("backend", "Backend"), 4, 0)
        self.overlay_combo(section, self.vars["capture_backend"], ["auto", "ddagrab", "gdigrab", "obs"], 4, 1)
        self.overlay_label(section, "Minecraft OBS mode", 5, 0)
        self.overlay_combo(section, self.vars["obs_minecraft_capture_mode"], ["specific_game", "display", "any_fullscreen"], 5, 1)
        self.overlay_check(section, "Capture desktop overlays (WGC)", self.vars["capture_desktop_overlays"], 6, 0, 3)
        self.overlay_hint(
            section,
            "Overlay capture includes Xbox Game Bar and desktop crosshairs. ShadowClip falls back automatically if WGC is black.",
            7,
        )

    def add_overlay_video_section(self, parent):
        section = self.overlay_section(parent, ui_text("video", "Video capture"))
        self.overlay_label(section, ui_text("clip", "Instant Replay length"), 1, 0)
        self.overlay_spinbox(section, self.vars["clip_seconds"], 1, 1, 10, 600, 10)
        self.overlay_label(section, ui_text("video", "Frame rate"), 1, 2)
        self.overlay_combo(section, self.vars["framerate"], [30, 60, 120, 144, 240], 1, 3, width=10)
        self.overlay_label(section, ui_text("quality", "Quality"), 2, 0)
        tk.Scale(
            section,
            variable=self.vars["quality"],
            from_=15,
            to=35,
            orient="horizontal",
            resolution=1,
            bg="#24292c",
            fg="#d7d7d7",
            troughcolor="#1b2023",
            highlightthickness=0,
            activebackground="#76b900",
        ).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=5)
        self.overlay_label(section, ui_text("replay", "Segment seconds"), 3, 0)
        self.overlay_spinbox(section, self.vars["segment_seconds"], 3, 1, 2, 15, 1)
        self.overlay_label(section, ui_text("ffmpeg", "Encoder"), 3, 2)
        self.overlay_combo(section, self.vars["video_encoder"], VIDEO_ENCODER_VALUES, 3, 3)
        self.overlay_label(section, ui_text("container", "Container"), 4, 0)
        self.overlay_combo(section, self.vars["container"], ["mkv", "mp4"], 4, 1, width=8)
        self.overlay_check(section, "Auto bitrate", self.vars["auto_video_bitrate"], 5, 0, columnspan=2)
        self.overlay_label(section, ui_text("quality", "Preset"), 5, 2)
        self.auto_bitrate_preset_combo_overlay = self.overlay_combo(section, self.vars["auto_bitrate_preset"], AUTO_BITRATE_PRESETS, 5, 3, width=12)
        self.overlay_label(section, ui_text("quality", "Bitrate mode"), 6, 0)
        self.bitrate_mode_combo_overlay = self.overlay_combo(section, self.vars["bitrate_mode"], ["quality", "target"], 6, 1, width=12)
        self.overlay_label(section, ui_text("video", "Target Mbps"), 6, 2)
        self.video_bitrate_spin_overlay = self.overlay_spinbox(section, self.vars["video_bitrate_mbps"], 6, 3, 1, 300, 1)
        self.overlay_label(section, ui_text("video", "Max Mbps"), 7, 2)
        self.max_bitrate_spin_overlay = self.overlay_spinbox(section, self.vars["max_bitrate_mbps"], 7, 3, 1, 500, 1)
        self.overlay_check(section, "Auto OBS replay RAM", self.vars["obs_replay_ram_auto"], 8, 0, columnspan=2)
        self.obs_replay_buffer_spin_overlay = self.overlay_spinbox(section, self.vars["obs_replay_buffer_mb"], 8, 2, 64, 2048, 64)
        self.sync_auto_video_bitrate(force=True)
        self.sync_auto_obs_replay_buffer(force=True)
        self.overlay_hint(
            section,
            "Auto bitrate uses resolution, frame rate, and preset; Auto OBS replay RAM uses clip length and the calculated target bitrate.",
            9,
        )

    def add_overlay_audio_section(self, parent):
        section = self.overlay_section(parent, ui_text("audio", "Audio"))
        self.overlay_check(section, ui_text("mic", "Mic"), self.vars["mic_enabled"], 1, 0)
        self.mic_combo_overlay = ttk.Combobox(section, textvariable=self.vars["mic_device"])
        self.mic_combo_overlay.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=5)
        self.overlay_button(section, ui_text("replay", "Scan"), self.scan_audio, 1, 3)
        self.overlay_check(section, ui_text("desktop", "Desktop audio"), self.vars["desktop_audio_enabled"], 2, 0)
        self.desktop_audio_combo_overlay = ttk.Combobox(section, textvariable=self.vars["desktop_audio_device"])
        self.desktop_audio_combo_overlay.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=5)
        self.overlay_combo(section, self.vars["desktop_audio_backend"], ["wasapi", "dshow"], 2, 3, width=8)
        self.overlay_label(section, ui_text("clip", "Clip audio offset ms"), 3, 0)
        self.overlay_spinbox(section, self.vars["audio_offset_ms"], 3, 1, -20000, 20000, 50)
        self.overlay_label(section, ui_text("record", "Recording audio offset ms"), 4, 0)
        self.overlay_spinbox(section, self.vars["recording_audio_offset_ms"], 4, 1, -20000, 20000, 50)
        self.overlay_hint(
            section,
            "Clip and recording offsets are separate so the replay buffer and manual recordings can stay in sync independently.",
            5,
        )

    def add_overlay_storage_section(self, parent):
        section = self.overlay_section(parent, ui_text("storage", "Storage and startup"))
        self.overlay_label(section, ui_text("folder", "Output"), 1, 0)
        self.overlay_entry(section, self.vars["output_dir"], 1, 1, columnspan=2)
        self.overlay_button(section, ui_text("browse", "Browse"), self.browse_output, 1, 3)
        self.overlay_label(section, ui_text("ffmpeg", "FFmpeg"), 2, 0)
        self.overlay_entry(section, self.vars["ffmpeg_path"], 2, 1, columnspan=2)
        self.overlay_button(section, ui_text("browse", "Browse"), self.browse_ffmpeg, 2, 3)
        self.overlay_label(section, "OBS", 3, 0)
        self.overlay_entry(section, self.vars["obs_path"], 3, 1, columnspan=2)
        self.overlay_button(section, ui_text("browse", "Browse"), self.browse_obs, 3, 3)
        self.overlay_label(section, ui_text("storage", "Max storage GB"), 4, 0)
        self.overlay_spinbox(section, self.vars["max_storage_gb"], 4, 1, 0, 5000, 5)
        self.overlay_check(section, ui_text("gallery", "Organize by game/app"), self.vars["organize_clips_by_game"], 5, 0, 2)
        self.overlay_check(section, ui_text("replay", "Reset replay window after clip"), self.vars["reset_replay_after_clip"], 6, 0, 2)
        self.overlay_check(section, ui_text("startup", "Start with Windows"), self.vars["start_with_windows"], 7, 0, 2)
        self.overlay_check(section, ui_text("replay", "Start replay on launch"), self.vars["auto_start_replay"], 7, 2, 2)
        self.overlay_check(section, ui_text("download", "Check updates on launch"), self.vars["check_updates_on_start"], 8, 0, 3)
        self.overlay_check(section, "Use per-game profiles", self.vars["use_game_profiles"], 9, 0, 3)
        self.overlay_button(section, "Save Game Profile", self.save_game_profile_for_current_game, 10, 0, columnspan=2)
        self.overlay_button(section, "Delete Profile", self.delete_game_profile_for_current_game, 10, 2, columnspan=2)
        self.overlay_button(section, "Check Setup", self.run_health_check, 11, 0, columnspan=2)
        self.overlay_button(section, "Export Debug Report", self.export_debug_report, 11, 2, columnspan=2)

    def add_overlay_interface_section(self, parent):
        section = self.overlay_section(parent, ui_text("settings", "HUD and Feedback"))
        self.overlay_label(section, ui_text("record", "Capture status icons"), 1, 0)
        self.overlay_check(section, "Show while replay or recording is active", self.vars["recording_indicator_enabled"], 1, 1, 2)
        self.overlay_label(section, ui_text("audio", "Toast duration ms"), 2, 0)
        self.overlay_spinbox(section, self.vars["toast_duration_ms"], 2, 1, 500, 10000, 250)
        self.overlay_label(section, ui_text("tray", "Toast position"), 2, 2)
        self.overlay_combo(section, self.vars["toast_position"], ["top_right", "bottom_right", "top_left", "bottom_left"], 2, 3, width=14)
        self.overlay_label(section, ui_text("gallery", "Gallery clips"), 3, 0)
        self.overlay_spinbox(section, self.vars["gallery_limit"], 3, 1, 3, 50, 1)
        self.overlay_check(section, ui_text("clip", "Close HUD after Save Clip"), self.vars["hide_overlay_after_clip"], 4, 0, 3)
        self.overlay_check(section, "Fullscreen-safe HUD", self.vars["fullscreen_safe_hud"], 5, 0, 3)
        self.overlay_check(section, "Event sound feedback", self.vars["event_sounds_enabled"], 6, 0, 3)
        self.overlay_hint(
            section,
            "Fullscreen-safe HUD avoids stealing focus from exclusive fullscreen games. In that mode, use hotkeys for actions and event sounds as feedback.",
            7,
        )

    def save_overlay_settings(self):
        self.save_settings()
        self.update_overlay_state()
        self.update_recording_indicator()

    def gallery_limit(self):
        try:
            return max(3, min(50, int(self.vars["gallery_limit"].get())))
        except (TypeError, ValueError, tk.TclError):
            return 12

    def toast_duration_ms(self):
        try:
            return max(500, min(10000, int(self.vars["toast_duration_ms"].get())))
        except (TypeError, ValueError, tk.TclError):
            return 2600

    def toast_position(self):
        position = str(self.vars["toast_position"].get() or "top_right")
        if position not in {"top_right", "bottom_right", "top_left", "bottom_left"}:
            return "top_right"
        return position

    def recording_indicator_enabled(self):
        try:
            return bool(self.vars["recording_indicator_enabled"].get())
        except tk.TclError:
            return True

    def event_sounds_enabled(self):
        try:
            return bool(self.vars["event_sounds_enabled"].get())
        except tk.TclError:
            return True

    def play_event_sound(self, icon_key="record", force=False):
        if (not force and not self.event_sounds_enabled()) or winsound is None:
            return
        sound_path = resource_path(EVENT_SOUND_FILES.get(icon_key, EVENT_SOUND_FILES["warning"]))
        if not sound_path.exists():
            return
        try:
            winsound.PlaySound(
                str(sound_path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except Exception:
            pass

    def preview_event_sound_set(self):
        for delay_ms, icon_key in ((0, "record"), (650, "clip"), (1300, "stop")):
            self.root.after(
                delay_ms,
                lambda event_key=icon_key: self.play_event_sound(event_key, force=True),
            )

    def show_event_toast(self, title, detail="", icon_key="record"):
        if self.root.winfo_exists():
            def display_toast():
                try:
                    self._show_event_toast(title, detail, icon_key)
                except Exception as exc:
                    self.threadsafe_log(f"Toast display failed: {exc}")

            self.root.after(0, display_toast)

    def _show_event_toast(self, title, detail="", icon_key="record"):
        self.play_event_sound(icon_key)
        self.destroy_event_toast()
        toast = tk.Toplevel(self.root)
        toast.withdraw()
        self.event_toast = toast
        toast.overrideredirect(True)
        transparent = "#010203"
        toast.configure(bg=transparent)
        toast.attributes("-topmost", True)
        try:
            toast.attributes("-alpha", 0.96)
            if os.name == "nt":
                toast.attributes("-transparentcolor", transparent)
        except tk.TclError:
            pass

        width = 338
        height = 74
        bounds = self.current_overlay_bounds()
        screen_w = bounds["width"]
        screen_h = bounds["height"]
        margin_x = 30
        margin_top = 72
        margin_bottom = 72
        position = self.toast_position()
        x = bounds["left"] + (margin_x if position.endswith("left") else max(0, screen_w - width - margin_x))
        y = bounds["top"] + (margin_top if position.startswith("top") else max(0, screen_h - height - margin_bottom))
        toast.geometry(f"{width}x{height}+{x}+{y}")

        frame = tk.Frame(
            toast,
            bg="#090d0b",
            width=328,
            height=64,
            highlightbackground="#32402d",
            highlightthickness=1,
        )
        frame.place(x=5, y=5, width=328, height=64)
        visual_key, color = FEEDBACK_ICON_STYLES.get(icon_key, FEEDBACK_ICON_STYLES["warning"])
        accent = tk.Frame(frame, bg=color, width=4)
        accent.pack(side="left", fill="y")
        icon = tk.Canvas(frame, width=38, height=38, bg="#090d0b", highlightthickness=0, bd=0)
        icon.pack(side="left", padx=(14, 12))
        self.draw_dashboard_icon(icon, visual_key, 38, color)
        text = tk.Frame(frame, bg="#090d0b")
        text.pack(side="left", fill="both", expand=True, padx=(0, 16), pady=(10, 9))
        title_label = tk.Label(
            text,
            text=title,
            bg="#090d0b",
            fg="#f4f7fb",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        title_label.pack(fill="x")
        detail_label = tk.Label(
            text,
            text=detail,
            bg="#090d0b",
            fg="#aeb8c6",
            anchor="w",
            font=("Segoe UI", 8),
        )
        detail_label.pack(fill="x", pady=(3, 0))
        toast._shadowclip_feedback = {
            "title": title,
            "detail": detail,
            "icon": icon,
            "title_label": title_label,
            "detail_label": detail_label,
        }

        self.keep_game_overlay_visible(toast, click_through=True, attempts=7, delay_ms=120)
        self.event_toast_after_ids.append(self.root.after(self.toast_duration_ms(), lambda: self.fade_event_toast(0.96)))

    def fade_event_toast(self, alpha):
        toast = self.event_toast
        if not toast or not toast.winfo_exists():
            return
        next_alpha = alpha - 0.08
        if next_alpha <= 0.08:
            self.destroy_event_toast()
            return
        try:
            toast.attributes("-alpha", next_alpha)
        except tk.TclError:
            self.destroy_event_toast()
            return
        self.event_toast_after_ids.append(self.root.after(24, lambda: self.fade_event_toast(next_alpha)))

    def destroy_event_toast(self):
        for after_id in self.event_toast_after_ids:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self.event_toast_after_ids = []
        if self.event_toast and self.event_toast.winfo_exists():
            try:
                self.event_toast.destroy()
            except tk.TclError:
                pass
        self.event_toast = None

    def add_overlay_tile(self, parent, key, title, action, row, column):
        button = tk.Button(
            parent,
            text=title,
            command=lambda: self.handle_overlay_action(action),
            width=19,
            height=6,
            bg="#0c110d",
            fg="#f1f1f1",
            activebackground="#1d2918",
            activeforeground="#ffffff",
            relief="solid",
            bd=1,
            highlightthickness=2,
            highlightbackground="#232b23",
            font=("Segoe UI Symbol", 11, "bold"),
            justify="center",
            cursor="hand2",
        )
        button.grid(row=row, column=column, padx=8, pady=4)
        self.overlay_buttons[key] = button
        self.bind_button_hover(
            button,
            hover_bg="#172415",
            hover_fg="#ffffff",
            hover_highlight="#76b900",
            hover_bd=1,
        )

    def add_overlay_quick_button(self, parent, key, title, action, column):
        button = tk.Button(
            parent,
            text=title,
            command=lambda: self.handle_overlay_action(action),
            bg="#0c110d",
            fg="#f1f1f1",
            activebackground="#1d2918",
            activeforeground="#ffffff",
            relief="flat",
            width=18,
            height=2,
            font=("Segoe UI Symbol", 9, "bold"),
            cursor="hand2",
        )
        button.grid(row=0, column=column, sticky="ew", padx=6)
        parent.columnconfigure(column, weight=1)
        self.overlay_buttons[key] = button
        self.bind_button_hover(
            button,
            hover_bg="#172415",
            hover_fg="#ffffff",
            hover_relief="solid",
            hover_bd=1,
        )

    def bind_button_hover(self, button, hover_bg="#30363a", hover_fg="#ffffff", hover_highlight=None, hover_relief=None, hover_bd=None):
        normal = {
            "bg": button.cget("bg"),
            "fg": button.cget("fg"),
            "relief": button.cget("relief"),
            "bd": button.cget("bd"),
        }
        try:
            normal["highlightbackground"] = button.cget("highlightbackground")
        except tk.TclError:
            pass

        def on_enter(_event):
            try:
                if not getattr(button, "_shadowclip_hover_active", False):
                    button._shadowclip_hover_active = True
                    button._shadowclip_normal_style = {
                        "bg": button.cget("bg"),
                        "fg": button.cget("fg"),
                        "relief": button.cget("relief"),
                        "bd": button.cget("bd"),
                    }
                    try:
                        button._shadowclip_normal_style["highlightbackground"] = button.cget("highlightbackground")
                    except tk.TclError:
                        pass
                button.configure(bg=hover_bg, fg=hover_fg)
                if hover_relief is not None:
                    button.configure(relief=hover_relief)
                if hover_bd is not None:
                    button.configure(bd=hover_bd)
                if hover_highlight is not None:
                    button.configure(highlightbackground=hover_highlight)
            except tk.TclError:
                pass

        def on_leave(_event):
            try:
                style = getattr(button, "_shadowclip_normal_style", normal)
                button.configure(bg=style.get("bg", normal["bg"]), fg=style.get("fg", normal["fg"]))
                button.configure(relief=style.get("relief", normal["relief"]), bd=style.get("bd", normal["bd"]))
                if "highlightbackground" in style:
                    button.configure(highlightbackground=style["highlightbackground"])
                button._shadowclip_hover_active = False
            except tk.TclError:
                pass

        button.bind("<Enter>", on_enter, add="+")
        button.bind("<Leave>", on_leave, add="+")

    def hide_overlay(self):
        if self.overlay and self.overlay.winfo_exists():
            self.overlay.withdraw()
        self.overlay_visible = False

    def update_overlay_state(self):
        if not self.overlay or not self.overlay.winfo_exists():
            return
        if hasattr(self, "overlay_toggle_label") and self.overlay_toggle_label:
            try:
                self.overlay_toggle_label.configure(text=self.hotkey_label("toggle_overlay").replace("+", " + "))
            except tk.TclError:
                pass
        if hasattr(self, "overlay_hint_label") and self.overlay_hint_label:
            try:
                if self.overlay_click_through:
                    hint_text = (
                        f"Fullscreen-safe mode: mouse disabled, use hotkeys | "
                        f"{self.hotkey_label('save_clip')} saves a clip"
                    )
                else:
                    hint_text = f"{self.hotkey_label('save_clip')} saves a clip"
                self.overlay_hint_label.configure(text=ui_text("hotkey", hint_text))
            except tk.TclError:
                pass
        replay_text = overlay_text("replay", "Instant Replay", "ON" if self.replay_running() else "OFF")
        recording_detail = self.recording_detail_label()
        record_detail = f"Recording {recording_detail}" if recording_detail else "Not recording"
        record_text = overlay_text("record", "Record", record_detail)
        mic_text = ui_text("mic", "Mic: ON" if bool(self.vars["mic_enabled"].get()) else "Mic: OFF")
        desktop_text = ui_text("desktop", "Desktop Audio: ON" if bool(self.vars["desktop_audio_enabled"].get()) else "Desktop Audio: OFF")
        self.set_overlay_button("replay", replay_text, self.replay_running())
        self.set_overlay_button("record", record_text, self.recording_running())
        self.set_overlay_button("clip", overlay_text("clip", "Save Clip", self.hotkey_label("save_clip")), False)
        self.set_overlay_button("gallery", overlay_text("gallery", "Gallery", "Open clips"), False)
        self.set_overlay_button("mic", mic_text, bool(self.vars["mic_enabled"].get()))
        self.set_overlay_button("desktop", desktop_text, bool(self.vars["desktop_audio_enabled"].get()))
        self.set_overlay_button("settings", ui_text("settings", "Settings"), False)

    def set_overlay_button(self, key, text, active):
        button = self.overlay_buttons.get(key)
        if not button:
            return
        if active:
            button.configure(text=text, highlightbackground="#76b900", bg="#182513")
        else:
            button.configure(text=text, highlightbackground="#232b23", bg="#0c110d")

    def handle_overlay_action(self, action):
        if action == "toggle_replay":
            self.toggle_replay()
        elif action == "save_clip":
            self.save_clip()
            if bool(self.vars["hide_overlay_after_clip"].get()):
                self.hide_overlay()
        elif action == "toggle_recording":
            self.toggle_recording()
        elif action == "open_gallery":
            self.show_overlay_gallery()
        elif action == "toggle_mic":
            self.vars["mic_enabled"].set(not bool(self.vars["mic_enabled"].get()))
            self.collect_config()
            self.threadsafe_log(f"Mic {'enabled' if self.vars['mic_enabled'].get() else 'disabled'} from HUD.")
        elif action == "toggle_desktop_audio":
            self.vars["desktop_audio_enabled"].set(not bool(self.vars["desktop_audio_enabled"].get()))
            self.collect_config()
            self.threadsafe_log(f"Desktop audio {'enabled' if self.vars['desktop_audio_enabled'].get() else 'disabled'} from HUD.")
        elif action == "show_settings":
            self.show_overlay_settings()
        self.update_overlay_state()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def hide_window(self, show_hint=True):
        self.hide_overlay()
        self.root.withdraw()
        self.status_var.set("Running in tray.")
        if show_hint and not self.tray_hint_shown:
            self.tray_hint_shown = True
            self.notify_user(APP_NAME, "ShadowClip is running in the tray.")

    def notify_user(self, title, message):
        if self.tray:
            self.tray.notify(title, message)

    def replay_running(self):
        return bool(self.manager.replay_proc and self.manager.replay_proc.poll() is None)

    def recording_running(self):
        return bool(self.manager.record_proc and self.manager.record_proc.poll() is None)

    def recording_elapsed_label(self):
        elapsed = self.manager.recording_elapsed_seconds()
        if elapsed is None:
            return ""
        return format_duration(elapsed)

    def recording_file_size_label(self):
        size = self.manager.current_recording_size()
        if not size:
            return ""
        return format_file_size(size)

    def recording_detail_label(self):
        elapsed = self.recording_elapsed_label()
        size = self.recording_file_size_label()
        parts = [part for part in (elapsed, size) if part]
        return " | ".join(parts)

    def tray_state(self):
        return {
            "replay": self.replay_running(),
            "recording": self.recording_running(),
        }

    def refresh_status_panel(self):
        replay_running = self.replay_running()
        recording_running = self.recording_running()
        self.replay_status_var.set(ui_text("replay", "Replay: Running" if replay_running else "Replay: Idle"))
        recording_text = "Recording: Idle"
        if recording_running:
            detail = self.recording_detail_label()
            recording_text = f"Recording: {detail}" if detail else "Recording: Running"
        self.recording_status_var.set(ui_text("record", recording_text))

        audio_parts = []
        if bool(self.vars["mic_enabled"].get()):
            audio_parts.append("Mic")
        if bool(self.vars["desktop_audio_enabled"].get()):
            audio_parts.append("Desktop")
        self.audio_status_var.set(ui_text("audio", f"Audio: {', '.join(audio_parts) if audio_parts else 'Off'}"))

        capture_mode = self.vars["capture_mode"].get()
        if capture_mode == "window":
            title = self.vars["window_title"].get().strip() or "Window"
            source_text = f"Source: {title[:28]}"
        elif capture_mode == "monitor":
            source_text = f"Source: Monitor {int(self.vars['monitor_index'].get()) + 1}"
        else:
            source_text = "Source: All screens"
        if bool(self.vars["capture_desktop_overlays"].get()):
            source_text += " + overlays"
        self.source_status_var.set(ui_text("source", source_text))

        try:
            max_storage_gb = float(self.vars["max_storage_gb"].get() or 0)
        except (TypeError, ValueError, tk.TclError):
            max_storage_gb = 0
        storage_mode = "Game folders" if bool(self.vars["organize_clips_by_game"].get()) else "Flat folder"
        if max_storage_gb > 0:
            storage_text = f"Storage: {max_storage_gb:g} GB"
        else:
            storage_text = f"Storage: {storage_mode}"
        self.storage_status_var.set(ui_text("storage", storage_text))

        if hasattr(self, "replay_button"):
            try:
                self.replay_button.configure(text=ui_text("stop" if replay_running else "replay", "Stop Replay" if replay_running else "Start Replay"))
            except tk.TclError:
                pass
        if hasattr(self, "recording_button"):
            try:
                self.recording_button.configure(text=ui_text("stop" if recording_running else "record", "Stop Recording" if recording_running else "Start Recording"))
            except tk.TclError:
                pass
        if hasattr(self, "home_replay_value"):
            self.update_home_dashboard()
        self.update_overlay_state()

    def tick_recording_timer(self):
        if self.is_quitting:
            return
        self.update_recording_indicator()
        if self.recording_running():
            self.refresh_status_panel()
        self.root.after(1000, self.tick_recording_timer)

    def update_recording_indicator(self):
        replay_active = self.replay_running()
        recording_active = self.recording_running()
        state = (replay_active, recording_active)
        if not any(state) or not self.recording_indicator_enabled():
            self.hide_recording_indicator()
            return
        if (
            not self.recording_indicator
            or not self.recording_indicator.winfo_exists()
            or self.recording_indicator_state != state
        ):
            self.build_recording_indicator(replay_active, recording_active)
        try:
            count = int(replay_active) + int(recording_active)
            width = 50 * count + 8 * max(0, count - 1)
            height = 50
            bounds = self.current_overlay_bounds()
            x = bounds["left"] + max(0, bounds["width"] - width - 26)
            y = bounds["top"] + max(0, bounds["height"] - height - 30)
            self.recording_indicator.geometry(f"{width}x{height}+{x}+{y}")
            self.show_window_game_overlay(self.recording_indicator, click_through=True)
        except tk.TclError:
            self.recording_indicator = None
            self.recording_indicator_state = None

    def build_recording_indicator(self, replay_active, recording_active):
        self.hide_recording_indicator()
        indicator = tk.Toplevel(self.root)
        indicator.withdraw()
        self.recording_indicator = indicator
        self.recording_indicator_state = (bool(replay_active), bool(recording_active))
        indicator.overrideredirect(True)
        transparent = "#010203"
        indicator.configure(bg=transparent)
        indicator.attributes("-topmost", True)
        try:
            indicator.attributes("-alpha", 0.70)
            if os.name == "nt":
                indicator.attributes("-transparentcolor", transparent)
        except tk.TclError:
            pass
        row = tk.Frame(indicator, bg=transparent)
        row.pack(fill="both", expand=True)
        states = []
        if replay_active:
            states.append(("replay", "#80d51a"))
        if recording_active:
            states.append(("record", "#ff4f64"))
        for index, (icon_key, color) in enumerate(states):
            tile = tk.Frame(
                row,
                bg="#070a08",
                width=50,
                height=50,
                highlightbackground="#32402d" if icon_key == "replay" else "#553039",
                highlightthickness=1,
            )
            tile.pack(side="left", padx=(0 if index == 0 else 8, 0))
            tile.pack_propagate(False)
            canvas = tk.Canvas(tile, width=30, height=30, bg="#070a08", highlightthickness=0, bd=0)
            canvas.place(relx=0.5, rely=0.5, anchor="center")
            self.draw_dashboard_icon(canvas, icon_key, 30, color)
        indicator._shadowclip_status_icons = states

    def hide_recording_indicator(self):
        if self.recording_indicator and self.recording_indicator.winfo_exists():
            try:
                self.recording_indicator.destroy()
            except tk.TclError:
                pass
        self.recording_indicator = None
        self.recording_indicator_state = None

    def update_tray_status(self):
        states = []
        if self.replay_running():
            states.append("Replay")
        if self.recording_running():
            states.append("Recording")
        state_text = ", ".join(states) if states else "Idle"
        tooltip = f"{APP_NAME} - {state_text}"
        if self.tray:
            self.tray.set_tooltip(tooltip)
        self.refresh_status_panel()
        self.update_recording_indicator()
        if not self.root.state() == "withdrawn":
            self.status_var.set(tooltip)

    def exit_app(self):
        self.is_quitting = True
        self.show_window()
        self.on_close()

    def threadsafe_log(self, message):
        self.log_queue.put(str(message))

    def drain_log_queue(self):
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            stamp = datetime.now().strftime("%H:%M:%S")
            line = f"[{stamp}] {message}\n"
            self.recent_log_lines.append(f"{stamp}    {message}")
            self.recent_log_lines = self.recent_log_lines[-24:]
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
            self.status_var.set(message)
            self.update_recent_logs_preview()
            self.update_status_bar()
            if message.startswith("Clip saved") or message.startswith("OBS recording saved:"):
                self.root.after(650, lambda: self.refresh_clip_library(force=True))
            if (
                message.startswith("Replay buffer")
                or message.startswith("Replay FFmpeg")
                or message.startswith("Replay auto-restart")
                or message.startswith("Stopped replay")
                or message.startswith("Recording started")
                or message.startswith("Stopped recording")
                or message.startswith("Forced recording")
                or message.startswith("No recording running")
                or message.startswith("Replay buffer is not running")
            ):
                self.update_tray_status()
            if message == "Replay buffer started.":
                self.notify_user("Replay started", "Replay buffer is running.")
                self.show_event_toast("Instant Replay started", "Replay capture is now active.", "replay")
                self.update_recording_indicator()
            elif message == "Stopped replay.":
                self.notify_user("Replay stopped", "Replay buffer stopped.")
                self.show_event_toast("Instant Replay stopped", "Replay capture is now inactive.", "stop")
                self.update_recording_indicator()
            elif message.startswith("Recording started:"):
                self.notify_user("Recording started", message)
                self.show_event_toast("Recording has started", "Full recording is now running.", "record")
                self.update_recording_indicator()
            elif message == "Stopped recording.":
                self.notify_user("Recording stopped", "Full recording stopped.")
                self.show_event_toast("Recording has stopped", "Full recording was saved.", "stop")
                self.update_recording_indicator()
            elif message == "Forced recording to stop.":
                self.notify_user("Recording stopped", "Full recording stopped.")
                self.show_event_toast("Recording has stopped", "Full recording was stopped.", "stop")
                self.update_recording_indicator()
            elif message.startswith("Clip saved"):
                self.notify_user("Clip saved", message)
                clip_detail = "Replay clip was saved."
                if "(" in message and "):" in message:
                    clip_detail = message.split("(", 1)[1].split("):", 1)[0]
                self.show_event_toast("Clip saved", clip_detail, "clip")
                self.refresh_status_panel()
                if self.overlay_mode == "gallery":
                    self.refresh_overlay_gallery()
            elif message.startswith("Clip save failed"):
                self.notify_user("Clip save failed", message)
                self.show_event_toast("Clip was not saved", message, "warning")
            elif message.startswith("OBS clip save failed:"):
                detail = message.split(":", 1)[1].strip() if ":" in message else message
                self.notify_user("Clip save failed", detail)
                self.show_event_toast("Clip was not saved", detail, "warning")
        self.root.after(100, self.drain_log_queue)

    def on_close(self):
        if self.capture_self_test_running:
            self.is_quitting = False
            self.show_window()
            messagebox.showinfo(APP_NAME, "Wait for the capture test to finish before exiting ShadowClip.", parent=self.root)
            return
        if self.tray and self.tray.hwnd and not self.is_quitting:
            self.hide_window()
            return
        if (self.manager.replay_proc and self.manager.replay_proc.poll() is None) or (
            self.manager.record_proc and self.manager.record_proc.poll() is None
        ):
            if not messagebox.askyesno(APP_NAME, "Recording or replay is still running. Stop and exit?"):
                self.is_quitting = False
                return
        if self.save_settings() is False:
            self.is_quitting = False
            return
        self.manager.stop_all()
        self.hotkeys.stop()
        if self.tray:
            self.tray.stop()
        self.destroy_event_toast()
        self.hide_recording_indicator()
        self.root.destroy()


def main():
    if os.name != "nt":
        raise SystemExit("ShadowClip is Windows-only.")
    single_instance_mutex = acquire_single_instance_mutex()
    if single_instance_mutex is False:
        return
    remove_legacy_startup_shortcut()
    save_config(load_config())
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = ShadowClipApp(root, start_minimized="--minimized" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()
