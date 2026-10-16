import json
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chitalka import processes
from chitalka.completion import complete
from chitalka.completion_support import install
from chitalka.sessions import list_sessions, stop_sessions


def proc(pid=12345, started="Fri Oct 16 18:00:00 2026", command="python /tmp/chitalka --root /tmp/paper", ppid=1):
    return processes.Process(pid, ppid, os.getuid(), "S", started, command)


class SessionTests(unittest.TestCase):
    def test_old_readers_and_tracked_orphan_builders(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"XDG_STATE_HOME": temp}):
            reader, child = proc(), proc(12346, command="latexmk -pvc", ppid=12345)
            table = {p.pid: p for p in (reader, child)}
            with patch.object(processes, "process_table", return_value=table):
                processes.register("chitalka", "latexmk", "/tmp/paper", pid=child.pid)
            with patch.object(processes, "cwd", return_value=Path("/tmp/paper")):
                items = list_sessions(table=table)
            self.assertEqual([s["pid"] for s in items], [reader.pid])
            self.assertEqual(items[0]["children"], [child.pid])
            orphan = list_sessions(table={child.pid: child})
            self.assertEqual([s["kind"] for s in orphan], ["latexmk"])

    def test_reused_pid_is_never_signalled(self):
        old, reused = proc(), proc(started="Fri Oct 16 19:00:00 2026", command="unrelated")
        with patch.object(processes, "process_table", return_value={old.pid: reused}), patch.object(processes.os, "kill") as kill:
            result = processes.terminate([old.pid], {old.pid: old}, timeout=0, force=True)
        kill.assert_not_called()
        self.assertFalse(result["remaining"])

    def test_stop_all_selection_only_includes_readers(self):
        reader, other = proc(), proc(12347, command="another-application")
        with patch("chitalka.sessions.process_table", return_value={reader.pid: reader, other.pid: other}), \
             patch.object(processes, "cwd", return_value=Path("/tmp/paper")), \
             patch("chitalka.sessions.terminate", return_value={"remaining": [], "stopped": [reader.pid]}) as stop:
            stop_sessions(all_sessions=True)
        self.assertEqual(stop.call_args.args[0], [reader.pid])

    def test_command_and_engine_completion(self):
        self.assertEqual(complete(["ses"]), ["sessions"])
        self.assertEqual(complete(["--engine", "xe"]), ["xelatex"])
        self.assertIn("--force", complete(["stop", "--f"]))

    def test_comment_ids_and_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="paper space ") as temp:
            root = Path(temp)
            (root / "kommentarii").mkdir()
            (root / "kommentarii/kommentarii.json").write_text(json.dumps([{"id": "abc123"}, {"id": "xyz"}]))
            self.assertEqual(complete(["reply", "--root", temp, "ab"]), ["abc123"])
            (root / "article name.pdf").touch()
            self.assertIn(str(root / "article name.pdf"), complete([str(root / "article")]))

    def test_completion_install_preserves_other_tool_block(self):
        with tempfile.TemporaryDirectory() as temp:
            rc = Path(temp) / ".zshrc"
            rc.write_text("# another tool\n")
            install("chitalka", "zsh", temp)
            first = rc.read_text()
            install("chitalka", "zsh", temp)
            self.assertEqual(rc.read_text(), first)
            self.assertIn("# another tool", first)


if __name__ == "__main__":
    unittest.main()
