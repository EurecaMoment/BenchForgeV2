"""Persist feature operations in the selected workspace."""
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from storage.files import write_json as write

class WorkspaceJobs:
    def __init__(self, workspace, config=None):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config or {}
        self.dsh_context = {'session_id': os.environ['BENCHFORGE_DSH_SESSION_ID'],
                            'call_id': os.environ.get('BENCHFORGE_DSH_CALL_ID', '')} if os.environ.get('BENCHFORGE_DSH_SESSION_ID') else {}
        self.db = sqlite3.connect(self.root / "runs.sqlite", timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, tool TEXT, state TEXT, artifact TEXT, error TEXT)")
        self.db.commit()

    def close(self):
        self.db.close()

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute one harness operation and persist its request and result."""
        if tool == "status":
            result = self.db.execute("SELECT id,tool,state,artifact,error FROM operations ORDER BY rowid DESC LIMIT 30").fetchall()
            return {"operations": [dict(zip(("id","tool","state","artifact","error"), row)) for row in result]}
        operation = uuid.uuid4().hex[:16]
        directory = self.root / "operations" / operation
        directory.mkdir(parents=True)
        self.db.execute("INSERT INTO operations VALUES (?,?,?,?,?)", (operation, tool, "running", str(directory), None))
        self.db.commit()
        write(directory / "request.json", {"tool": tool, "arguments": args, "time": datetime.now(timezone.utc).isoformat(), "context": self.dsh_context})
        try:
            value = self.execute(tool, {**args, '_dsh_context': self.dsh_context} if self.dsh_context else args, directory)
            write(directory / "result.json", value)
            self.db.execute("UPDATE operations SET state='completed' WHERE id=?", (operation,))
            self.db.commit()
            return {"operation_id": operation, "artifact_dir": str(directory), **value}
        except Exception as exc:
            self.db.execute("UPDATE operations SET state='failed',error=? WHERE id=?", (str(exc), operation))
            self.db.commit()
            raise
