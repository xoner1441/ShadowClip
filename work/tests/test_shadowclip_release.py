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
        app.keep_game_overlay_visible = (
            lambda window, **_kwargs: app.show_window_game_overlay(
                window,
                click_through=True,
            )
        )
        try:
            with mock.patch.object(SHADOWCLIP.os, "name", "posix"):
                app._show_event_toast("Clip saved", "Replay clip was saved.", "clip")
                app.update_recording_indicator()
                root.update()
            self.assertNotEqual(app.event_toast.state(), "withdrawn")
            self.assertNotEqual(app.recording_indicator.state(), "withdrawn")
            self.assertGreater(app.event_toast.winfo_width(), 300)
            self.assertEqual(
                app.event_toast._shadowclip_feedback["title"],
                "Clip saved",
            )
            self.assertAlmostEqual(
                float(app.recording_indicator.attributes("-alpha")),
                0.70,
                places=2,
            )
            self.assertEqual(app.recording_indicator_state, (True, False))
        finally:
            app.destroy_event_toast()
            root.destroy()

    @unittest.skipUnless(SHADOWCLIP.os.name == "nt", "Windows overlay styles are required")
    def test_persistent_status_overlay_is_click_through_on_native_toplevel(self):
        root = SHADOWCLIP.tk.Tk()
        root.withdraw()
        app = object.__new__(SHADOWCLIP.ShadowClipApp)
        app.root = root
        app.noactivate_window_procs = {}
        app.click_through_hwnds = set()
        overlay = SHADOWCLIP.tk.Toplevel(root)
        overlay.withdraw()
        overlay.overrideredirect(True)
        SHADOWCLIP.tk.Frame(overlay, width=50, height=50).pack()
        overlay.geometry("50x50+100+100")
        overlay.deiconify()
        root.update()
        try:
            app.set_window_game_overlay_style(overlay, click_through=True)
            root.update_idletasks()
            handles = app.native_window_handles(overlay)
            self.assertGreaterEqual(len(handles), 2)
            top_level_hwnd = SHADOWCLIP.wintypes.HWND(handles[-1])
            user32 = SHADOWCLIP.ctypes.windll.user32
            get_window_long = user32.GetWindowLongPtrW
            get_window_long.argtypes = [SHADOWCLIP.wintypes.HWND, SHADOWCLIP.ctypes.c_int]
            get_window_long.restype = SHADOWCLIP.ctypes.c_ssize_t
            style = int(get_window_long(top_level_hwnd, SHADOWCLIP.GWL_EXSTYLE))
            self.assertTrue(style & SHADOWCLIP.WS_EX_TRANSPARENT)
            self.assertTrue(style & SHADOWCLIP.WS_EX_NOACTIVATE)
            self.assertTrue(style & SHADOWCLIP.WS_EX_TOOLWINDOW)
            self.assertTrue(style & SHADOWCLIP.WS_EX_LAYERED)
            user32.SendMessageW.argtypes = [
                SHADOWCLIP.wintypes.HWND,
                SHADOWCLIP.wintypes.UINT,
                SHADOWCLIP.wintypes.WPARAM,
                SHADOWCLIP.wintypes.LPARAM,
            ]
            user32.SendMessageW.restype = SHADOWCLIP.LRESULT
            hit_test = int(user32.SendMessageW(top_level_hwnd, SHADOWCLIP.WM_NCHITTEST, 0, 0))
            self.assertEqual(hit_test, SHADOWCLIP.HTTRANSPARENT)

            app.set_window_game_overlay_style(overlay, click_through=False)
            style = int(get_window_long(top_level_hwnd, SHADOWCLIP.GWL_EXSTYLE))
            self.assertFalse(style & SHADOWCLIP.WS_EX_TRANSPARENT)
        finally:
            overlay.destroy()
            root.update_idletasks()
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

    def test_obs_fragmented_mp4_is_finalized_for_seekable_playback(self):
        ffmpeg = SOURCE_PATH.parent / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        if not ffmpeg.exists():
            self.skipTest("Bundled FFmpeg is not available")
        config = dict(SHADOWCLIP.DEFAULT_CONFIG)
        config.update({"ffmpeg_path": str(ffmpeg), "max_storage_gb": 0})
        messages = []
        manager = SHADOWCLIP.FfmpegManager(config, messages.append)
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "obs-hybrid.mp4"
            result = subprocess.run(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-f", "lavfi",
                    "-i", "testsrc2=size=320x180:rate=30:duration=4",
                    "-f", "lavfi",
                    "-i", "sine=frequency=880:sample_rate=48000:duration=4",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-shortest",
                    "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                    str(source),
                ],
                capture_output=True,
                creationflags=SHADOWCLIP.CREATE_NO_WINDOW,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertTrue(SHADOWCLIP.mp4_needs_seek_finalization(source))

            output = manager.finalize_obs_media_for_seeking(source, "Clip")

            self.assertEqual(output, source)
            self.assertFalse(SHADOWCLIP.mp4_needs_seek_finalization(output))
            boxes = SHADOWCLIP.mp4_top_level_box_types(output)
            self.assertLess(boxes.index("moov"), boxes.index("mdat"))
            self.assertNotIn("moof", boxes)
            self.assertTrue(manager.has_video_stream(output))
            self.assertTrue(manager.has_audio_stream(output))
            seek_result = subprocess.run(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-loglevel", "error",
                    "-ss", "2.0",
                    "-i", str(output),
                    "-frames:v", "1",
                    "-f", "null",
                    "-",
                ],
                capture_output=True,
                creationflags=SHADOWCLIP.CREATE_NO_WINDOW,
            )
            self.assertEqual(seek_result.returncode, 0, seek_result.stderr.decode(errors="replace"))
            self.assertIn("Clip finalized for seekable playback.", messages)

    def test_seekable_faststart_mp4_is_not_rewritten(self):
        ffmpeg = SOURCE_PATH.parent / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        if not ffmpeg.exists():
            self.skipTest("Bundled FFmpeg is not available")
        config = dict(SHADOWCLIP.DEFAULT_CONFIG)
        config.update({"ffmpeg_path": str(ffmpeg), "max_storage_gb": 0})
        messages = []
        manager = SHADOWCLIP.FfmpegManager(config, messages.append)
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "faststart.mp4"
            result = subprocess.run(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-f", "lavfi",
                    "-i", "testsrc2=size=320x180:rate=30:duration=1",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    str(source),
                ],
                capture_output=True,
                creationflags=SHADOWCLIP.CREATE_NO_WINDOW,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            original_hash = SHADOWCLIP.sha256_file(source)
            self.assertFalse(SHADOWCLIP.mp4_needs_seek_finalization(source))

            manager.finalize_obs_media_for_seeking(source, "Clip")

            self.assertEqual(SHADOWCLIP.sha256_file(source), original_hash)
            self.assertEqual(messages, [])

    def test_log_queue_processing_is_bounded_and_history_is_trimmed(self):
        class FakeRoot:
            def __init__(self):
                self.delays = []

            def after(self, delay, _callback):
                self.delays.append(delay)

        class FakeValue:
            def set(self, _value):
                pass

        class FakeLog:
            def __init__(self):
                self.delete_calls = 0

            def configure(self, **_kwargs):
                pass

            def insert(self, *_args):
                pass

            def delete(self, *_args):
                self.delete_calls += 1

            def see(self, *_args):
                pass

        app = object.__new__(SHADOWCLIP.ShadowClipApp)
        app.root = FakeRoot()
        app.log_queue = SHADOWCLIP.queue.Queue()
        app.recent_log_lines = []
        app.ui_log_line_count = 2190
        app.log_text = FakeLog()
        app.status_var = FakeValue()
        app.update_recent_logs_preview = mock.Mock()
        app.update_status_bar = mock.Mock()
        for index in range(150):
            app.log_queue.put(f"performance test {index}")

        app.drain_log_queue()

        self.assertEqual(app.log_queue.qsize(), 50)
        self.assertEqual(app.root.delays[-1], 10)
        self.assertLessEqual(app.ui_log_line_count, 2200)
        self.assertGreater(app.log_text.delete_calls, 0)

    def test_gallery_thumbnail_memory_cache_is_bounded(self):
        app = object.__new__(SHADOWCLIP.ShadowClipApp)
        app.clip_gallery_thumbnail_images = {
            f"signature-{index}": object()
            for index in range(80)
        }
        app.redraw_clip_card_preview = mock.Mock()

        class FakeCanvas:
            pass

        canvas = FakeCanvas()
        signature = "signature-79"
        app.load_clip_gallery_thumbnail("clip", canvas, signature, "unused.png")

        self.assertLessEqual(len(app.clip_gallery_thumbnail_images), 72)
        self.assertIn(signature, app.clip_gallery_thumbnail_images)
        self.assertIs(canvas._shadowclip_preview_image, app.clip_gallery_thumbnail_images[signature])


if __name__ == "__main__":
    unittest.main(verbosity=2)
