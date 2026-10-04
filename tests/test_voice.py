import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from brain.commands import Action, Command
from core.loop import LightLoop
from core.state import LightState
from voice.handy import Handy


class TestHandyVoiceAndLoop(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "history.db"

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE transcription_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcription_text TEXT
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_database_raises_error(self):
        missing_path = Path(self.temp_dir.name) / "nonexistent.db"
        with self.assertRaises(FileNotFoundError):
            Handy(db_path=missing_path)

    def test_empty_history_returns_none(self):
        handy = Handy(db_path=self.db_path)
        self.assertIsNone(handy.get_latest_transcription())

    def test_returns_latest_transcription(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO transcription_history (transcription_text) VALUES (?)",
            ("Open YouTube",),
        )
        conn.execute(
            "INSERT INTO transcription_history (transcription_text) VALUES (?)",
            ("Search for Coldplay",),
        )
        conn.commit()
        conn.close()

        handy = Handy(db_path=self.db_path)
        latest = handy.get_latest_transcription()

        self.assertIsNotNone(latest)
        self.assertEqual(latest["id"], 2)
        self.assertEqual(latest["text"], "Search for Coldplay")

    def test_malformed_database_table_raises_runtime_error(self):
        bad_db = Path(self.temp_dir.name) / "bad.db"
        conn = sqlite3.connect(bad_db)
        conn.execute("CREATE TABLE wrong_table (id INTEGER)")
        conn.commit()
        conn.close()

        handy = Handy(db_path=bad_db)
        with self.assertRaises(RuntimeError):
            handy.get_latest_transcription()

    def test_loop_duplicate_handling_and_error_recovery(self):
        handy = MagicMock()
        # Simulate: initial None, then ID 1 ("Scroll down"), then ID 2 (immediate duplicate "Scroll down"),
        # then DB error, then ID 3 ("How are you" -> ignored), then ID 4 ("Stop")
        handy.get_latest_transcription.side_effect = [
            None,
            {"id": 1, "text": "Scroll down"},
            {"id": 2, "text": "Scroll down"},
            RuntimeError("Database locked"),
            {"id": 3, "text": "How are you"},
            {"id": 4, "text": "Stop"},
        ]

        laya = MagicMock()

        def fake_understand(text, state=None):
            if text == "Scroll down":
                return Command(Action.SCROLL, "down")
            if text == "Stop":
                return Command(Action.STOP, None)
            raise ValueError("Ignored casual speech")

        laya.understand.side_effect = fake_understand

        executor = MagicMock()
        state = LightState()
        executor.state = state

        def fake_execute(cmd, raw_text=None):
            state.record_command(raw_text, cmd)
            return "STOP" if cmd.action == Action.STOP else "OK"

        executor.execute.side_effect = fake_execute

        loop = LightLoop(
            handy=handy,
            laya=laya,
            executor=executor,
            state=state,
            duplicate_cooldown=5.0,
        )
        loop.run(max_iterations=10)

        # Verify "Scroll down" was only executed ONCE (ID 2 was debounced) and "Stop" was executed once
        self.assertEqual(executor.execute.call_count, 2)
        executor.browser.close.assert_called_once()

    @patch("main.atexit.register")
    @patch("main.subprocess.run")
    def test_ensure_single_instance_kills_stale_pids_and_writes_current_pid(
        self,
        mock_run,
        _mock_atexit,
    ):
        from main import ensure_single_instance

        pid_file = Path(self.temp_dir.name) / ".light.pid"
        pid_file.write_text("9264", encoding="utf-8")

        def fake_run(cmd, **kwargs):
            res = MagicMock()
            res.returncode = 0
            if cmd[0] == "powershell":
                res.stdout = f"9264\n25168\n{os.getpid()}\n"
            elif cmd[0] == "ps":
                res.stdout = f"9264 0 python main.py\n25168 0 python main.py\n{os.getpid()} 0 python main.py\n"
            else:
                res.stdout = ""
            return res

        mock_run.side_effect = fake_run

        killed = ensure_single_instance(pid_file=pid_file)
        self.assertEqual(killed, [9264, 25168])
        self.assertEqual(pid_file.read_text(encoding="utf-8").strip(), str(os.getpid()))


if __name__ == "__main__":
    unittest.main()
