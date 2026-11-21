"""Browser support for the web build (pygbag / WebAssembly).

In the browser there are no threads, no clipboard access from Python and no
sockets, so this module talks to the page's JavaScript instead:

- BrowserPeer: the WebSocket connection (same interface as NetPeer)
- ask_text: a native text prompt, which also opens the phone keyboard
- copy_text / post_json: clipboard and HTTP POST through JavaScript

On the desktop IS_WEB is False and nothing here is used.
"""

import json
import sys

IS_WEB = sys.platform == "emscripten"

_JS = r"""
if (!window.pw) {
  window.pw = {
    q: [], ws: null, state: "idle", pending: [], results: {},
    connect(url) {
      this.q = []; this.pending = []; this.state = "connecting";
      let ws;
      try { ws = new WebSocket(url); } catch (e) { this.state = "closed"; return; }
      this.ws = ws;
      ws.onopen = () => { this.state = "open"; for (const m of this.pending) ws.send(m); this.pending = []; };
      ws.onmessage = (e) => { this.q.push(e.data); };
      ws.onclose = () => { this.state = "closed"; };
      ws.onerror = () => { this.state = "closed"; };
    },
    send(s) {
      if (this.ws && this.ws.readyState === 1) this.ws.send(s);
      else if (this.state === "connecting") this.pending.push(s);
    },
    poll() { const out = JSON.stringify(this.q); this.q = []; return out; },
    close() { if (this.ws) { try { this.ws.close(); } catch (e) {} } this.ws = null; this.state = "closed"; },
    ask(message, value) { const r = window.prompt(message, value); return r === null ? "\u0000" : r; },
    copy(s) {
      try { navigator.clipboard.writeText(s); return "1"; } catch (e) { return "0"; }
    },
    post(id, url, body) {
      this.results[id] = "";
      fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body })
        .then(r => { this.results[id] = r.ok ? "ok" : ("error " + r.status); })
        .catch(e => { this.results[id] = "error " + e; });
    },
    result(id) { const r = this.results[id]; if (r) delete this.results[id]; return r || ""; },
    // Where the last tap / click really happened, in canvas pixels. SDL reports the last *hover*
    // position for button events, which is wrong for taps (a finger doesn't hover first).
    ptr: null,
    trackPointer() {
      const c = document.getElementById("canvas");
      if (!c || this.tracking) return;
      this.tracking = true;
      const f = (e) => {
        const r = c.getBoundingClientRect();
        this.ptr = [Math.round((e.clientX - r.left) * c.width / r.width),
                    Math.round((e.clientY - r.top) * c.height / r.height)];
      };
      c.addEventListener("pointerdown", f, true);
      c.addEventListener("pointermove", f, true);
    },
    pointer() { return JSON.stringify(this.ptr); },
  };
}
"""

_ready = False


def js(code):
    """Run JavaScript in the page and return its (string / number) result."""
    global _ready
    import platform  # pygbag's platform module exposes the page's `window`
    if not _ready:
        platform.window.eval(_JS)
        _ready = True
    return platform.window.eval(code)


def track_pointer():
    """Start recording real tap positions (call once the canvas exists)."""
    js("pw.trackPointer()")


def pointer_pos():
    """(x, y) of the last tap / click on the canvas, in window pixels, or None."""
    try:
        p = json.loads(str(js("pw.pointer()")))
        return (int(p[0]), int(p[1])) if p else None
    except Exception:
        return None


def is_portrait():
    try:
        return str(js("(innerHeight > innerWidth * 1.1) ? '1' : '0'")) == "1"
    except Exception:
        return False


def page_origin():
    """e.g. https://proximity-wars.onrender.com (the server that hosts the page)."""
    try:
        return str(js("window.location.origin"))
    except Exception:
        return ""


def ask_text(message, value=""):
    """Native browser prompt (opens the on-screen keyboard). Returns None if cancelled."""
    r = js(f"pw.ask({json.dumps(message)}, {json.dumps(value)})")
    r = "" if r is None else str(r)
    return None if r == "\u0000" else r


def copy_text(s):
    try:
        return str(js(f"pw.copy({json.dumps(s)})")) == "1"
    except Exception:
        return False


_post_ids = [0]


def post_json(url, payload):
    """Start a POST; returns an id to pass to post_result() on later frames."""
    _post_ids[0] += 1
    pid = f"p{_post_ids[0]}"
    js(f"pw.post({json.dumps(pid)}, {json.dumps(url)}, {json.dumps(json.dumps(payload))})")
    return pid


def post_result(pid):
    """"" while waiting, then "ok" or "error ..."."""
    return str(js(f"pw.result({json.dumps(pid)})") or "")


class BrowserPeer:
    """WebSocket connection through the browser (same interface as NetPeer)."""

    def __init__(self, url):
        self.url = url
        self.running = True
        js(f"pw.connect({json.dumps(url)})")

    def send(self, message):
        if self.running:
            js(f"pw.send({json.dumps(json.dumps(message, separators=(',', ':')))})")

    def poll(self):
        raw = js("pw.poll()")
        messages = []
        try:
            items = json.loads(str(raw)) if raw else []
        except json.JSONDecodeError:
            items = []
        for item in items:
            try:
                messages.append(json.loads(item))
            except json.JSONDecodeError:
                pass
        if str(js("pw.state")) == "closed" and not messages:
            self.running = False
        return messages

    def close(self):
        self.running = False
        try:
            js("pw.close()")
        except Exception:
            pass
