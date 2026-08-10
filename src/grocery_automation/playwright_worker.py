from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from grocery_automation.config import default_worker_dir

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright


class WorkerUnavailable(RuntimeError):
    pass


@dataclass
class BrowserSession:
    browser: Any
    context: Any
    page: Any
    headed: bool
    storage_state_path: Optional[Path]


def worker_runtime_dir() -> Path:
    override = os.environ.get("GROCERY_WORKER_DIR")
    if override:
        return Path(override).expanduser()
    return default_worker_dir()


def worker_socket_path() -> Path:
    return worker_runtime_dir() / "playwright-worker.sock"


def worker_pid_path() -> Path:
    return worker_runtime_dir() / "playwright-worker.pid"


def worker_log_path() -> Path:
    return worker_runtime_dir() / "playwright-worker.log"


def _clean_stale_runtime_files() -> None:
    pid_path = worker_pid_path()
    socket_path = worker_socket_path()
    if not pid_path.exists():
        if socket_path.exists():
            socket_path.unlink()
        return
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        pid = -1
    if pid <= 0:
        pid_path.unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, 0)
    except OSError:
        pid_path.unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)


def request_worker(method: str, params: Optional[dict[str, Any]] = None, *, timeout: float = 10.0) -> Any:
    payload = {"method": method, "params": params or {}}
    socket_path = worker_socket_path()
    if not socket_path.exists():
        raise WorkerUnavailable("Playwright worker is not running.")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        try:
            client.connect(str(socket_path))
        except (OSError, socket.timeout) as exc:
            raise WorkerUnavailable(f"Could not connect to the Playwright worker: {exc}") from exc
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        response = b""
        while not response.endswith(b"\n"):
            try:
                chunk = client.recv(65536)
            except socket.timeout as exc:
                raise WorkerUnavailable(
                    f"Timed out waiting for the Playwright worker to respond to {method!r}."
                ) from exc
            if not chunk:
                break
            response += chunk
    if not response:
        raise WorkerUnavailable("Playwright worker closed the connection without a response.")
    try:
        data = json.loads(response.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkerUnavailable("Playwright worker returned invalid JSON.") from exc
    if not data.get("ok"):
        error = str(data.get("error") or "unknown worker error")
        raise WorkerUnavailable(error)
    return data.get("result")


def ensure_worker_running(timeout: float = 15.0) -> None:
    try:
        request_worker("ping", timeout=1.0)
        return
    except WorkerUnavailable:
        pass

    runtime_dir = worker_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _clean_stale_runtime_files()
    log_handle = worker_log_path().open("a")
    subprocess.Popen(
        [sys.executable, "-m", "grocery_automation.playwright_worker", "--serve"],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    deadline = time.time() + timeout
    last_error = "worker did not start"
    while time.time() < deadline:
        try:
            request_worker("ping", timeout=1.0)
            return
        except WorkerUnavailable as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise WorkerUnavailable(f"Timed out waiting for the Playwright worker: {last_error}")


class GroceryPlaywrightWorker:
    def __init__(self) -> None:
        self._playwright_cm: Any = None
        self._playwright: Optional[Playwright] = None
        self._sessions: dict[str, BrowserSession] = {}

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The Python Playwright package is not installed. Install project dependencies first."
            ) from exc
        self._playwright_cm = sync_playwright()
        self._playwright = self._playwright_cm.start()

    def shutdown(self) -> None:
        for session_name in list(self._sessions):
            self._close_session(session_name)
        if self._playwright is not None:
            self._playwright_cm.stop()
            self._playwright = None

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        if method == "ping":
            return {"pid": os.getpid(), "sessions": sorted(self._sessions)}
        if method == "status":
            return {
                "pid": os.getpid(),
                "socket": str(worker_socket_path()),
                "sessions": sorted(self._sessions),
            }
        if method == "stop":
            result = {"stopping": True, "sessions": sorted(self._sessions)}
            self.shutdown()
            return result
        if method == "ensure_session":
            return self._ensure_session(
                session=str(params["session"]),
                url=str(params["url"]),
                headed=bool(params.get("headed", False)),
                storage_state_path=_optional_path(params.get("storage_state_path")),
            )
        if method == "goto":
            session = self._require_session(str(params["session"]))
            session.page.goto(str(params["url"]), wait_until="domcontentloaded")
            return self._page_info(session.page)
        if method == "eval":
            session = self._require_session(str(params["session"]))
            value = session.page.evaluate(str(params["expression"]))
            return {"value": value, **self._page_info(session.page)}
        if method == "save_storage_state":
            session = self._require_session(str(params["session"]))
            output = Path(str(params["path"])).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            session.context.storage_state(path=str(output))
            session.storage_state_path = output
            return {"path": str(output)}
        if method == "close_session":
            self._close_session(str(params["session"]))
            return {"closed": True}
        raise RuntimeError(f"Unknown worker method {method!r}")

    def _page_info(self, page: Any) -> dict[str, Any]:
        return {
            "page_url": page.url,
            "page_title": page.title(),
        }

    def _require_session(self, session_name: str) -> BrowserSession:
        try:
            return self._sessions[session_name]
        except KeyError as exc:
            raise RuntimeError(f"Unknown session {session_name!r}.") from exc

    def _close_session(self, session_name: str) -> None:
        session = self._sessions.pop(session_name, None)
        if session is None:
            return
        try:
            session.context.close()
        finally:
            session.browser.close()

    def _launch_browser(self, *, headed: bool) -> Any:
        if self._playwright is None:
            raise RuntimeError("Playwright worker has not been started.")
        launch_kwargs = {"headless": not headed}
        try:
            from playwright.sync_api import Error
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The Python Playwright package is not installed. Install project dependencies first."
            ) from exc
        try:
            return self._playwright.chromium.launch(channel="chrome", **launch_kwargs)
        except Error:
            try:
                return self._playwright.chromium.launch(**launch_kwargs)
            except Error as exc:
                raise RuntimeError(
                    "Could not launch Chromium. Install Playwright browsers with "
                    "`python -m playwright install chromium` or make Chrome available locally."
                ) from exc

    def _ensure_session(
        self,
        *,
        session: str,
        url: str,
        headed: bool,
        storage_state_path: Optional[Path],
    ) -> dict[str, Any]:
        existing = self._sessions.get(session)
        resolved_storage = storage_state_path.expanduser() if storage_state_path else None
        if existing is not None:
            same_storage = existing.storage_state_path == resolved_storage
            if existing.headed == headed and same_storage:
                if url and not existing.page.url:
                    existing.page.goto(url, wait_until="domcontentloaded")
                return self._page_info(existing.page)
            self._close_session(session)

        browser = self._launch_browser(headed=headed)
        context_kwargs: dict[str, Any] = {}
        if resolved_storage and resolved_storage.exists():
            context_kwargs["storage_state"] = str(resolved_storage)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        if url:
            page.goto(url, wait_until="domcontentloaded")
        self._sessions[session] = BrowserSession(
            browser=browser,
            context=context,
            page=page,
            headed=headed,
            storage_state_path=resolved_storage,
        )
        return self._page_info(page)


def _optional_path(value: Any) -> Optional[Path]:
    if not value:
        return None
    return Path(str(value))


def _serve_forever() -> None:
    runtime_dir = worker_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _clean_stale_runtime_files()
    socket_path = worker_socket_path()
    socket_path.unlink(missing_ok=True)
    pid_path = worker_pid_path()
    pid_path.write_text(f"{os.getpid()}\n")

    worker = GroceryPlaywrightWorker()
    worker.start()
    should_stop = False
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(socket_path))
        socket_path.chmod(0o600)
        server.listen()
        while not should_stop:
            conn, _ = server.accept()
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                if not data:
                    continue
                try:
                    request = json.loads(data.decode("utf-8"))
                    result = worker.handle(
                        str(request.get("method", "")),
                        dict(request.get("params") or {}),
                    )
                    response = {"ok": True, "result": result}
                    if request.get("method") == "stop":
                        should_stop = True
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                conn.sendall(json.dumps(response).encode("utf-8") + b"\n")
    worker.shutdown()
    socket_path.unlink(missing_ok=True)
    pid_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal Playwright worker")
    parser.add_argument("--serve", action="store_true", help="Run the long-lived worker process")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.serve:
        parser.print_help()
        return
    _serve_forever()


if __name__ == "__main__":
    main()
