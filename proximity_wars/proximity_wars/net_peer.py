import json
import socket
import threading


class NetPeer:
    """Threaded newline-delimited JSON transport over TCP."""

    def __init__(self, sock):
        self.sock = sock
        self.sock.settimeout(0.5)
        self.send_lock = threading.Lock()
        self.inbox = []
        self.inbox_lock = threading.Lock()
        self.running = True
        self.buffer = b""
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def send(self, message):
        raw = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        with self.send_lock:
            try:
                self.sock.sendall(raw)
            except OSError:
                self.running = False

    def poll(self):
        with self.inbox_lock:
            messages = self.inbox[:]
            self.inbox.clear()
        return messages

    def _reader(self):
        while self.running:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    self.running = False
                    break
                self.buffer += chunk
                while b"\n" in self.buffer:
                    line, self.buffer = self.buffer.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    with self.inbox_lock:
                        self.inbox.append(message)
            except socket.timeout:
                continue
            except OSError:
                self.running = False
                break

    def close(self):
        self.running = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
