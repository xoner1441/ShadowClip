import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = REPO_ROOT / "work" / "ShadowClip" / "ShadowClip.py"
SPEC = importlib.util.spec_from_file_location("shadowclip_release_test", SOURCE_PATH)
SHADOWCLIP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SHADOWCLIP
SPEC.loader.exec_module(SHADOWCLIP)


class ReleaseLogicTests(unittest.TestCase):
    def test_release_version_beats_its_release_candidates(self):
        self.assertTrue(SHADOWCLIP.is_newer_version("0.1.21", "0.1.21-rc32"))
        self.assertTrue(SHADOWCLIP.is_newer_version("0.1.22", "0.1.21-rc32"))
        self.assertFalse(SHADOWCLIP.is_newer_version("0.1.21-rc32", "0.1.21"))

    def test_release_candidate_ordering(self):
        self.assertTrue(SHADOWCLIP.is_newer_version("0.1.21-rc32", "0.1.21-rc31"))
        self.assertTrue(SHADOWCLIP.is_newer_version("0.1.21-rc1", "0.1.21-beta9"))
        self.assertFalse(SHADOWCLIP.is_newer_version("v0.1.22", "0.1.22"))

    def test_update_asset_selection_prefers_shadowclip_setup(self):
        release = {
            "assets": [
                {"name": "notes.txt"},
                {"name": "OtherSetup.exe"},
                {"name": "ShadowClipSetup-0.1.22.exe"},
            ]
        }
        selected = SHADOWCLIP.choose_update_asset(release)
        self.assertEqual(selected["name"], "ShadowClipSetup-0.1.22.exe")

    def test_github_sha256_digest_parsing(self):
        value = "a" * 64
        self.assertEqual(
            SHADOWCLIP.parse_asset_sha256({"digest": f"sha256:{value}"}),
            value,
        )
        self.assertEqual(SHADOWCLIP.parse_asset_sha256({"digest": "sha256:nope"}), "")

    def test_automatic_video_and_ram_recommendations(self):
        self.assertEqual(
            SHADOWCLIP.recommended_video_bitrate_mbps(60, 1920, 1080, "high"),
            35,
        )
        self.assertEqual(
            SHADOWCLIP.recommended_video_bitrate_mbps(120, 1920, 1080, "high"),
            70,
        )
        self.assertEqual(SHADOWCLIP.recommended_obs_replay_buffer_mb(120, 35), 640)

    def test_standalone_and_combination_hotkeys(self):
        self.assertEqual(SHADOWCLIP.parse_hotkey_text("F9")[2], "F9")
        self.assertEqual(SHADOWCLIP.parse_hotkey_text("K")[2], "K")
        self.assertEqual(
            SHADOWCLIP.parse_hotkey_text("Ctrl + Alt + F9")[2],
            "Ctrl+Alt+F9",
        )

    def test_path_and_game_name_sanitization(self):
        self.assertEqual(
            SHADOWCLIP.friendly_application_name("FortniteClient-Win64-Shipping.exe"),
            "Fortnite",
        )
        self.assertEqual(SHADOWCLIP.sanitize_path_part('Bad:<Name>?'), "Bad Name")

    def test_default_config_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.json"
            path.write_text(
                json.dumps(SHADOWCLIP.DEFAULT_CONFIG, indent=2),
                encoding="utf-8",
            )
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["capture_backend"], "obs")
        self.assertEqual(loaded["hotkeys"]["save_clip"], "F9")


if __name__ == "__main__":
    unittest.main(verbosity=2)
