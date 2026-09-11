"""
esp32_link.py - transport to the robot's ESP32.

The rest of the stack never imports this module; only hardware_bridge.py does.
It hides whether the ESP32 is plugged in over USB serial or reachable over
Wi-Fi TCP, and it hides the line protocol framing.

PROTOCOL (plain ASCII, one message per line, '\\n' terminated)
--------------------------------------------------------------
Host -> ESP32
    CMD,<linear_mps>,<angular_rps>     velocity setpoint, e.g. CMD,0.300,-0.150
    PING,<seq>                         liveness probe
    RST                                zero the encoder counters
    CFG,<key>,<value>                  runtime tweak (e.g. CFG,kp,1.2)

ESP32 -> Host
    ENC,<left_ticks>,<right_ticks>,<millis>   cumulative counts + ESP32 clock
    BAT,<volts>                                battery voltage
    DIST,<centimetres>                         front range sensor (optional)
    PONG,<seq>                                 reply to PING
    VER,<string>                               firmware version, sent on connect
    ERR,<string>                               fault report
    LOG,<string>                               free-text debug

Design rules that make this robust:
  * Text, not binary  -> you can debug it with a serial monitor or `nc`.
  * Cumulative tick counts, not deltas -> a dropped line self-heals on the
    next message instead of permanently corrupting odometry.
  * The ESP32 timestamps its own messages -> tick deltas are divided by the
    ESP32's own dt, so host-side jitter does not distort velocity.
  * The ESP32 stops the motors if no CMD arrives for `watchdog_ms`.
"""

import socket
import threading
import time

try:
    import serial  # pyserial; only needed for the USB transport
except ImportError:  # pragma: no cover - allowed to be missing in sim-only setups
    serial = None


class LinkError(Exception):
    """Raised when the transport is broken and should be reconnected."""


class _BaseLink(object):
    """Common line buffering. Subclasses provide _read_bytes/_write_bytes."""

    def __init__(self):
        self._buf = b""
        self._lock = threading.Lock()
        self.connected = False

    # -- to be implemented by subclasses ---------------------------------
    def _connect(self):
        raise NotImplementedError

    def _read_bytes(self, n):
        raise NotImplementedError

    def _write_bytes(self, data):
        raise NotImplementedError

    def _close(self):
        raise NotImplementedError

    # -- public API -------------------------------------------------------
    def connect(self):
        self._close_quietly()
        self._buf = b""
        self._connect()
        self.connected = True

    def close(self):
        self._close_quietly()
        self.connected = False

    def _close_quietly(self):
        try:
            self._close()
        except Exception:
            pass

    def send_line(self, line):
        """Send one already-formatted command (no trailing newline needed)."""
        if not self.connected:
            raise LinkError("send on closed link")
        payload = (line + "\n").encode("ascii")
        with self._lock:
            try:
                self._write_bytes(payload)
            except Exception as exc:
                self.connected = False
                raise LinkError("write failed: %s" % exc)

    def read_lines(self):
        """Non-blocking-ish: return every COMPLETE line received so far.

        A partial tail stays in the buffer until its newline shows up, so a
        message split across two TCP packets is never mangled.
        """
        if not self.connected:
            raise LinkError("read on closed link")
        try:
            chunk = self._read_bytes(4096)
        except socket.timeout:
            chunk = b""
        except Exception as exc:
            self.connected = False
            raise LinkError("read failed: %s" % exc)

        if chunk:
            self._buf += chunk

        lines = []
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            text = raw.decode("ascii", errors="replace").strip()
            if text:
                lines.append(text)

        # Guard against a peer that never sends a newline (would grow forever)
        if len(self._buf) > 8192:
            self._buf = b""
        return lines

    # -- convenience command builders ------------------------------------
    def send_velocity(self, linear, angular):
        self.send_line("CMD,%.4f,%.4f" % (linear, angular))

    def send_ping(self, seq):
        self.send_line("PING,%d" % seq)

    def send_reset(self):
        self.send_line("RST")


class SerialLink(_BaseLink):
    """ESP32 over USB. Simplest and most reliable; use it while bringing up."""

    def __init__(self, port, baud=115200, timeout=0.0):
        _BaseLink.__init__(self)
        if serial is None:
            raise LinkError("pyserial is not installed: pip install pyserial")
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self._ser = None

    def _connect(self):
        self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        # Many ESP32 boards reset when the port opens; give the bootloader time.
        time.sleep(2.0)
        self._ser.reset_input_buffer()

    def _read_bytes(self, n):
        waiting = self._ser.in_waiting
        if not waiting:
            return b""
        return self._ser.read(min(waiting, n))

    def _write_bytes(self, data):
        self._ser.write(data)

    def _close(self):
        if self._ser is not None:
            self._ser.close()
            self._ser = None


class TcpLink(_BaseLink):
    """ESP32 over Wi-Fi. The ESP32 runs a TCP server; we are the client.

    Untethered, but adds Wi-Fi latency and jitter - that is exactly why the
    ESP32 timestamps its own encoder messages.
    """

    def __init__(self, host, port=9000, timeout=0.05):
        _BaseLink.__init__(self)
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None

    def _connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=3.0)
        self._sock.settimeout(self.timeout)
        # Velocity commands are tiny and latency-critical: never buffer them.
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def _read_bytes(self, n):
        data = self._sock.recv(n)
        if data == b"":
            raise LinkError("peer closed the connection")
        return data

    def _write_bytes(self, data):
        self._sock.sendall(data)

    def _close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None


class LoopbackLink(_BaseLink):
    """A fake ESP32 that lives in this process.

    Lets you run the FULL real-robot pipeline (hardware_bridge -> "ESP32" ->
    odometry -> navigation) with no hardware attached, which is how you debug
    the bridge itself before the board arrives.  It integrates the commanded
    velocity into encoder ticks using the same geometry as the real robot.
    """

    def __init__(self, ticks_per_rev, wheel_radius, wheel_separation):
        _BaseLink.__init__(self)
        self.ticks_per_rev = float(ticks_per_rev)
        self.wheel_radius = float(wheel_radius)
        self.wheel_separation = float(wheel_separation)
        self._lin = 0.0
        self._ang = 0.0
        self._left = 0.0
        self._right = 0.0
        self._t0 = time.time()
        self._last = time.time()
        self._outbox = []

    def _connect(self):
        self._outbox.append("VER,loopback-1.0")

    def _close(self):
        self._outbox = []

    def _write_bytes(self, data):
        for line in data.decode("ascii").splitlines():
            parts = line.strip().split(",")
            if parts[0] == "CMD" and len(parts) >= 3:
                self._lin, self._ang = float(parts[1]), float(parts[2])
            elif parts[0] == "PING" and len(parts) >= 2:
                self._outbox.append("PONG,%s" % parts[1])
            elif parts[0] == "RST":
                self._left = self._right = 0.0

    def _read_bytes(self, n):
        now = time.time()
        dt = now - self._last
        if dt >= 0.02:  # emit at ~50 Hz like the firmware does
            self._last = now
            v_l = self._lin - self._ang * self.wheel_separation / 2.0
            v_r = self._lin + self._ang * self.wheel_separation / 2.0
            k = self.ticks_per_rev / (2.0 * 3.14159265358979 * self.wheel_radius)
            self._left += v_l * dt * k
            self._right += v_r * dt * k
            ms = int((now - self._t0) * 1000.0)
            self._outbox.append("ENC,%d,%d,%d" % (int(self._left), int(self._right), ms))
            if int(ms / 1000) % 2 == 0 and ms % 1000 < 25:
                self._outbox.append("BAT,%.2f" % (8.2 - 0.0001 * (now - self._t0)))
        if not self._outbox:
            return b""
        out = ("\n".join(self._outbox) + "\n").encode("ascii")
        self._outbox = []
        return out


def make_link(params):
    """Factory driven by the `transport` field of config/hardware.yaml."""
    transport = params.get("transport", "loopback")
    if transport == "serial":
        return SerialLink(params["serial_port"], params.get("baud_rate", 115200))
    if transport == "tcp":
        return TcpLink(params["esp32_ip"], params.get("esp32_port", 9000))
    if transport == "loopback":
        return LoopbackLink(
            params.get("ticks_per_rev", 780.0),
            params.get("wheel_radius", 0.0325),
            params.get("wheel_separation", 0.16),
        )
    raise LinkError("unknown transport %r (use serial|tcp|loopback)" % transport)
