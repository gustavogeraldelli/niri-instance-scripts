import contextlib
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
with patch.dict(os.environ, SETUP_INSTANCES_CONFIG=str(ROOT / "config.example.json")):
    import window_ops as ops
from x11_pointer import aim


def script(name):
    return runpy.run_path(str(ROOT / "bin" / name))


class Pointer:
    width = height = 240

    def __init__(self, title="01-alpha"):
        self.x, self.y = 83., 170.

    def position(self):
        return round(self.x), round(self.y)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class PointerTests(unittest.TestCase):
    def test_consecutive_clicks_use_measured_client_center(self):
        pointer, clicks = Pointer(), []

        def send(args):
            if args[0] == "mousemove":
                pointer.x += int(args[-2]) * .85
                pointer.y += int(args[-1]) * .85
            else:
                clicks.append(pointer.position())

        with patch("x11_pointer.X11Pointer", return_value=pointer), \
             patch.object(ops, "unit_focus", return_value=1), \
             patch.object(ops, "assert_focused"), \
             patch.object(ops, "_ydotool", side_effect=send), \
             patch.object(ops.time, "sleep"):
            ops.unit_left_click("01-alpha", offset_y=22)
            ops.unit_double_click("01-alpha", offset_y=-94)
        for actual, expected in zip(clicks, [(120, 142), (120, 26)]):
            self.assertLessEqual(abs(actual[0] - expected[0]), 1)
            self.assertLessEqual(abs(actual[1] - expected[1]), 1)
        self.assertEqual(len(clicks), 2)

    def test_outside_or_unreachable_target_cancels(self):
        for start, target in [((10, 10), (250, 10)),
                              ((-1, 10), (120, 120)),
                              ((10, 10), (120, 120))]:
            pointer = Pointer()
            pointer.x, pointer.y = start
            with self.assertRaises(RuntimeError):
                aim(pointer, target, Mock(), Mock(), Mock())

    def test_lost_focus_never_sends_a_click(self):
        send = Mock()
        with patch("x11_pointer.X11Pointer", return_value=Pointer()), \
             patch.object(ops, "unit_focus", return_value=1), \
             patch.object(ops, "assert_focused", side_effect=ops.ScriptError("lost focus")), \
             patch.object(ops, "_ydotool", send), patch.object(ops.time, "sleep"):
            with self.assertRaises(ops.ScriptError):
                ops.unit_left_click("01-alpha")
        send.assert_not_called()

    def test_duplicate_title_is_refused(self):
        window = {"id": 1, "title": "01-alpha", "app_id": ops.APP_ID}
        with patch.object(ops, "all_windows", return_value=[window, dict(window, id=2)]):
            with self.assertRaises(ops.ScriptError):
                ops.unit_window("01-alpha")


class SequenceTests(unittest.TestCase):
    def test_pipeline_waits_per_target_and_opens_menu_before_item(self):
        ns = script("configure-instances")
        clock, events = [0.], []

        def sleep(seconds):
            clock[0] += seconds

        def record(stage):
            return lambda title, *args, **kwargs: events.append((stage, title, clock[0]))

        globals_ = ns["pipeline"].__globals__
        with patch.dict(globals_, unit_window_id=lambda t: 1, unit_focus=Mock(),
                        focused_window=lambda: {"id": 1},
                        unit_key=record("key"), unit_right_click=record("menu"),
                        unit_left_click=record("item")), \
             patch.object(ops.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(ops.time, "sleep", side_effect=sleep), \
             patch.dict(os.environ, SETUP_INSTANCES_WAIT_GUI="0.8",
                        SETUP_INSTANCES_WAIT_STAGE="3", SETUP_INSTANCES_WAIT_KEY="3",
                        SETUP_INSTANCES_WAIT_BETWEEN_WINDOWS="0"), \
             contextlib.redirect_stdout(io.StringIO()):
            result = ns["pipeline"](["01-alpha", "02-beta"], False, from_selector=True)
        self.assertEqual(set(result.values()), {"OK"})
        for title in result:
            own = [(stage, at) for stage, t, at in events if t == title]
            self.assertEqual(own[0][0], "menu")
            self.assertEqual(own[1][0], "item")
            self.assertGreaterEqual(own[1][1] - own[0][1], .8 - 1e-8)
            self.assertGreaterEqual(own[2][1] - own[1][1], 3 - 1e-8)
            self.assertGreaterEqual(own[3][1] - own[2][1], 3 - 1e-8)
        self.assertLess(events.index(next(e for e in events if e[:2] == ("item", "02-beta"))),
                        events.index(next(e for e in events if e[:2] == ("key", "01-alpha"))))

    def test_failed_selector_skips_later_actions_for_that_target(self):
        ns = script("configure-instances")
        key = Mock()
        with patch.dict(ns["pipeline"].__globals__, unit_window_id=lambda t: 1,
                        unit_focus=Mock(), focused_window=lambda: {"id": 1},
                        unit_key=key, unit_right_click=Mock(),
                        unit_left_click=Mock(side_effect=ops.ScriptError("lost cursor"))), \
             patch.object(ops.time, "sleep"), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            result = ns["pipeline"](["01-alpha"], False, from_selector=True)
        self.assertTrue(result["01-alpha"].startswith("ERRO"))
        key.assert_not_called()

    def test_join_preflight_failure_sends_no_clicks_to_any_target(self):
        ns = script("join-server")
        join = Mock()
        with patch.dict(ns["main"].__globals__, join=join,
                        validate_pre_grid_size=Mock(side_effect=ops.ScriptError("wrong size"))), \
             patch.object(sys, "argv", ["join-server", "--all"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ns["main"](), 1)
        join.assert_not_called()

    def test_failed_launch_stops_complete_sequence(self):
        ns = script("setup-instances")
        run = Mock(return_value=Mock(returncode=1))
        with patch.dict(ns["main"].__globals__, target_windows=lambda: []), \
             patch("subprocess.run", run), \
             patch.object(sys, "argv", ["setup-instances"]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ops.ScriptError):
                ns["main"]()
        self.assertEqual(run.call_count, 1)
        self.assertTrue(run.call_args.args[0][0].endswith("launch-instances"))

    def test_launch_dry_run_needs_no_desktop_and_starts_no_process(self):
        ns = script("launch-instances")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "unit-01").mkdir()
            with patch.dict(ns["main"].__globals__, INSTANCE_ROOT=Path(tmp),
                            target_windows=Mock(side_effect=AssertionError("desktop queried"))), \
                 patch("subprocess.Popen") as launch, \
                 patch.object(sys, "argv", ["launch-instances", "--only", "01-alpha", "--dry-run"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ns["main"](), 0)
            launch.assert_not_called()


class GridTests(unittest.TestCase):
    def test_sizes_keep_width_uniform_and_reset_heights(self):
        ns = script("arrange-grid")
        action = Mock()
        with patch.dict(ns["set_sizes"].__globals__, niri_action=action,
                        unit_window_id=lambda t: 1), patch.object(ops.time, "sleep"):
            ns["set_sizes"](["01-alpha"])
        self.assertEqual(action.call_args_list[0].args, ("reset-window-height", "--id", 1))
        self.assertEqual(action.call_args_list[1].args,
                         ("set-window-width", "240", "--id", 1))

    def test_final_grid_rejects_wrong_row_order(self):
        ns = script("arrange-grid")
        with patch.dict(ns["main"].__globals__,
                        target_windows=lambda: [{"title": "01-alpha"}, {"title": "03-alpha"}],
                        snapshot=Mock(), ensure_workspace=Mock(),
                        move_targets_to_workspace=Mock(), cleanup_legacy_workspace=Mock(),
                        split_existing_columns=Mock(), order_columns=Mock(),
                        build_column=Mock(), set_sizes=Mock(), focused_action=Mock(),
                        position=lambda t: (1, 1)):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ops.ScriptError):
                ns["main"]()


if __name__ == "__main__":
    unittest.main()
