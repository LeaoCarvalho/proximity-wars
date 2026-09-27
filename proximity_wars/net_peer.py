import json
import threading
import websocket


class NetPeer:
    """Threaded JSON WebSocket transport for the Pygame client."""

    def __init__(self, url):
        self.url = url
        self.inbox = []
        self.inbox_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.running = True

        self.ws = websocket.create_connection(url, timeout=12)
        self.ws.settimeout(0.5)

        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def send(self, message):
        if not self.running:
            return
        try:
            payload = json.dumps(message, separators=(",", ":"))
            with self.send_lock:
                self.ws.send(payload)
        except Exception:
            self.running = False

    def poll(self):
        with self.inbox_lock:
            messages = self.inbox[:]
            self.inbox.clear()
        return messages

    def _reader(self):
        while self.running:
            try:
                payload = self.ws.recv()
                if not payload:
                    self.running = False
                    break
                try:
                    message = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                with self.inbox_lock:
                    self.inbox.append(message)
            except Exception as exc:
                # websocket-client uses WebSocketTimeoutException for its
                # normal polling timeout. Any other exception means the
                # connection is gone.
                if exc.__class__.__name__ == "WebSocketTimeoutException":
                    continue
                self.running = False
                break

    def close(self):
        self.running = False
        try:
            self.ws.close()
        except Exception:
            pass
