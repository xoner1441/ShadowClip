import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
        self.assertTrue(loaded["capture_desktop_overlays"])
        self.assertTrue(loaded["capture_desktop_overlays_migrated"])

    def test_legacy_overlay_setting_is_migrated_once(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.json"
            path.write_text(
                json.dumps({"capture_desktop_overlays": False}),
                encoding="utf-8",
            )
            with mock.patch.object(SHADOWCLIP, "CONFIG_PATH", path):
                loaded = SHADOWCLIP.load_config()
        self.assertTrue(loaded["capture_desktop_overlays"])
        self.assertTrue(loaded["capture_desktop_overlays_migrated"])

    def test_explicit_overlay_choice_survives_after_migration(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "capture_desktop_overlays": False,
                        "capture_desktop_overlays_migrated": True,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(SHADOWCLIP, "CONFIG_PATH", path):
                loaded = SHADOWCLIP.load_config()
        self.assertFalse(loaded["capture_desktop_overlays"])

    def test_trim_range_is_clamped_and_keeps_a_minimum_selection(self):
        self.assertEqual(
            SHADOWCLIP.clamp_trim_range(-5, 200, 120),
            (0.0, 120.0),
        )
        start, end = SHADOWCLIP.clamp_trim_range(119.9, 119.95, 120)
        self.assertAlmostEqual(start, 119.75)
        self.assertAlmostEqual(end, 120.0)

    def test_precise_duration_format(self):
        self.assertEqual(SHADOWCLIP.format_precise_duration(65.432), "01:05.432")

    def test_fast_trim_command_stream_copies_video_and_audio(self):
        manager = object.__new__(SHADOWCLIP.FfmpegManager)
        manager.config = dict(SHADOWCLIP.DEFAULT_CONFIG)
        with mock.patch.object(manager, "require_ffmpeg", return_value="ffmpeg"):
            command = manager.build_media_trim_command(
                "input.mp4",
                "output.mp4",
                5,
                12.5,
                accurate=False,
                include_audio=True,
            )
        self.assertIn("-ss", command)
        self.assertIn("5.000", command)
        self.assertIn("-t", command)
        self.assertIn("7.500", command)
        self.assertIn("-c", command)
        self.assertIn("copy", command)
        self.assertIn("0:a?", command)

    def test_accurate_trim_command_encodes_video_and_audio(self):
        manager = object.__new__(SHADOWCLIP.FfmpegManager)
        manager.config = dict(SHADOWCLIP.DEFAULT_CONFIG)
        with (
            mock.patch.object(manager, "require_ffmpeg", return_value="ffmpeg"),
            mock.patch.object(
                manager,
                "encoder_args",
                return_value=["-c:v", "libx264"],
            ),
        ):
            command = manager.build_media_trim_command(
                "input.mp4",
                "output.mp4",
                1,
                4,
                accurate=True,
                include_audio=True,
            )
        self.assertIn("libx264", command)
        self.assertIn("-c:a", command)
        self.assertIn("aac", command)
        self.assertNotIn("copy", command)

    def test_explicit_alt_z_hud_hotkey_survives_config_reload(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.json"
            path.write_text(
                json.dumps({"hotkeys": {"toggle_overlay": "Alt+Z"}}),
                encoding="utf-8",
            )
            with mock.patch.object(SHADOWCLIP, "CONFIG_PATH", path):
                loaded = SHADOWCLIP.load_config()
        self.assertEqual(loaded["hotkeys"]["toggle_overlay"], "Alt+Z")

    def test_pulse_deep_event_sound_assets_are_present(self):
        self.assertEqual(
            set(SHADOWCLIP.EVENT_SOUND_FILES),
            {"clip", "record", "replay", "stop", "warning"},
        )
        for relative_path in set(SHADOWCLIP.EVENT_SOUND_FILES.values()):
            asset = SOURCE_PATH.parent / relative_path
            self.assertTrue(asset.exists(), asset)
            self.assertGreater(asset.stat().st_size, 40_000, asset)

    def test_reveal_clip_targets_the_exact_media_file(self):
        app = object.__new__(SHADOWCLIP.ShadowClipApp)
        app.threadsafe_log = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary_directory:
            clip = Path(temporary_directory) / "Game Clip.mp4"
            clip.write_bytes(b"clip")
            with mock.patch.object(SHADOWCLIP, "reveal_file_in_explorer") as reveal:
                app.reveal_clip_path(clip)
                reveal.assert_called_once_with(clip.resolve())

    def test_explorer_select_parameters_quote_paths_with_spaces(self):
        path = Path(r"F:\ShadowClip\Game Name\Game Clip.mp4")
        self.assertEqual(
            SHADOWCLIP.explorer_select_parameters(path),
            f'/select,"{path.resolve()}"',
        )

    def test_new_capture_feedback_windows_leave_withdrawn_state(self):
        root = SHADOWCLIP.tk.Tk()
        root.withdraw()
        app = object.__new__(SHADOWCLIP.ShadowClipApp)
        app.root = root
        app.event_toast = None
        app.event_toast_after_ids = []
        app.recording_indicator = None
        app.recording_indicator_state = None
        app.noactivate_window_procs = {}
        app.play_event_sound = mock.Mock()
        app.threadsafe_log = mock.Mock()
        app.toast_duration_ms = lambda: 10_000
        app.toast_position = lambda: "top_right"
        app.current_overlay_bounds = lambda: {
            "left": 0,
            "top": 0,
            "width": 1280,
            "height": 720,
        }
        app.replay_running = lambda: True
        app.recording_running = lambda: False
        app.recording_indicator_enabled = lambda: True
        app.set_window_game_overlay_style = mock.Mock()
        try:
            with mock.patch.object(SHADOWCLIP.os, "name", "posix"):
                app._show_event_toast("Clip saved", "Replay clip was saved.", "clip")
                app.update_recording_indicator()
                root.update()
            self.assertNotEqual(app.event_toast.state(), "withdrawn")
            self.assertNotEqual(app.recording_indicator.state(), "withdrawn")
            self.assertEqual(app.recording_indicator_state, (True, False))
        finally:
            root.destroy()

    def test_gallery_search_and_filter_controls_remain_available(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        for marker in (
            "self.clip_search_var",
            "self.clip_game_filter_var",
            "self.clip_kind_filter_var",
            "self.clip_sort_var",
            "Search clips...",
            "def scan_clip_library_worker",
        ):
            self.assertIn(marker, source)

    def test_clip_editor_exports_seekable_media_with_audio(self):
        ffmpeg = (
            SOURCE_PATH.parent
            / "tools"
            / "ffmpeg"
            / "bin"
            / "ffmpeg.exe"
        )
        if not ffmpeg.exists():
            self.skipTest("Bundled FFmpeg is not available")
        config = dict(SHADOWCLIP.DEFAULT_CONFIG)
        config.update(
            {
                "ffmpeg_path": str(ffmpeg),
                "video_encoder": "libx264",
                "max_storage_gb": 0,
            }
        )
        manager = SHADOWCLIP.FfmpegManager(config, lambda _message: None)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.mp4"
            fast_output = root / "fast.mp4"
            accurate_output = root / "accurate.mp4"
            result = subprocess.run(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x180:rate=30:duration=4",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=880:sample_rate=48000:duration=4",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(source),
                ],
                capture_output=True,
                creationflags=SHADOWCLIP.CREATE_NO_WINDOW,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            manager.trim_media(source, 1.0, 3.0, fast_output, accurate=False)
            manager.trim_media(source, 0.4, 2.6, accurate_output, accurate=True)
            for output, expected in ((fast_output, 2.0), (accurate_output, 2.2)):
                self.assertTrue(output.exists())
                self.assertTrue(manager.has_video_stream(output))
                self.assertTrue(manager.has_audio_stream(output))
                duration = manager.probe_duration(output)
                self.assertIsNotNone(duration)
                self.assertLess(abs(duration - expected), 0.35)


if __name__ == "__main__":
    unittest.main(verbosity=2)
