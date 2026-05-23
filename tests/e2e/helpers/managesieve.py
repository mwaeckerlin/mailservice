"""Minimal ManageSieve client (RFC 5804) using only stdlib."""
import base64
import socket
import re


class ManageSieveError(Exception):
    pass


class ManageSieveClient:
    def __init__(self, host: str, port: int = 4190, timeout: int = 10):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._buf = b""
        self._capabilities: dict[str, str] = {}
        self._read_capabilities()

    # ------------------------------------------------------------------ I/O --

    def _recv_line(self) -> str:
        while b"\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ManageSieveError("Connection closed unexpectedly")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\r\n", 1)
        return line.decode()

    def _send(self, data: str) -> None:
        self._sock.sendall((data + "\r\n").encode())

    def _read_response(self) -> tuple[str, str]:
        """Return (status, message) where status is OK / NO / BYE."""
        while True:
            line = self._recv_line()
            m = re.match(r'^(OK|NO|BYE)(?:\s+"?(.+?)"?)?$', line)
            if m:
                return m.group(1), m.group(2) or ""
            # skip capability / info lines

    def _read_capabilities(self) -> None:
        """Parse the greeting capability block until OK."""
        while True:
            line = self._recv_line()
            if line.startswith("OK"):
                break
            m = re.match(r'^"([^"]+)"\s*(?:"([^"]*)")?', line)
            if m:
                self._capabilities[m.group(1)] = m.group(2) or ""

    # ------------------------------------------------------------ Commands --

    def authenticate(self, username: str, password: str) -> None:
        credentials = base64.b64encode(
            f"\x00{username}\x00{password}".encode()
        ).decode()
        self._send(f'AUTHENTICATE "PLAIN" "{credentials}"')
        status, msg = self._read_response()
        if status != "OK":
            raise ManageSieveError(f"Authentication failed: {msg}")

    def put_script(self, name: str, script: str) -> None:
        encoded = script.encode()
        self._send(f'PUTSCRIPT "{name}" {{{len(encoded)}+}}')
        self._sock.sendall(encoded + b"\r\n")
        status, msg = self._read_response()
        if status != "OK":
            raise ManageSieveError(f"PUTSCRIPT failed: {msg}")

    def set_active(self, name: str) -> None:
        self._send(f'SETACTIVE "{name}"')
        status, msg = self._read_response()
        if status != "OK":
            raise ManageSieveError(f"SETACTIVE failed: {msg}")

    def list_scripts(self) -> list[str]:
        self._send("LISTSCRIPTS")
        scripts = []
        while True:
            line = self._recv_line()
            if line.startswith("OK"):
                break
            m = re.match(r'^"([^"]+)"', line)
            if m:
                scripts.append(m.group(1))
        return scripts

    def delete_script(self, name: str) -> None:
        self._send(f'DELETESCRIPT "{name}"')
        status, msg = self._read_response()
        if status != "OK":
            raise ManageSieveError(f"DELETESCRIPT failed: {msg}")

    def logout(self) -> None:
        self._send("LOGOUT")
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self.logout()
        except Exception:
            pass
