#!/usr/bin/env python3
"""devbox dashboard: processes, resources and auto-hibernate state.

Stdlib only; reads /proc directly, so it runs on any Linux box with python3.
Sections that don't apply (no idle checker, no IMDS) come back as null.

  python3 server.py [--bind 0.0.0.0] [--port 9999]
"""
import argparse
import calendar
import collections
import json
import os
import pwd
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
NPROC = os.cpu_count() or 1

SAMPLE_SEC = 5
HISTORY = 720  # 1 h of samples
TOP_N = 15

IDLE_CHECK = "/usr/local/bin/devbox-idle-check"
IDLE_CONF = "/etc/devbox/idle.conf"
IDLE_COUNT = "/var/lib/devbox-idle/count"
IDLE_LOG = "/var/log/devbox-idle.log"
HEARTBEAT_DIR = "/var/lib/devbox-activity"
IDLE_INTERVAL_MIN = 5  # must match devbox-idle.timer

REAL_FS = {"xfs", "ext4", "ext3", "btrfs", "vfat", "zfs", "f2fs"}


def safe(fn, *args):
    """Collectors return None instead of raising: missing files and permission
    errors are expected on boxes that aren't a devbox."""
    try:
        return fn(*args)
    except Exception:
        return None


def read(path):
    with open(path) as f:
        return f.read()


# ---- system -------------------------------------------------------------------

def cpu_times():
    """{'cpu': (busy, total), 'cpu0': ...} from /proc/stat."""
    out = {}
    for line in read("/proc/stat").splitlines():
        if not line.startswith("cpu"):
            break
        name, *vals = line.split()
        vals = [int(v) for v in vals]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals[:8])  # guest time is already inside user/nice
        out[name] = (total - idle, total)
    return out


def meminfo():
    m = {}
    for line in read("/proc/meminfo").splitlines():
        k, v = line.split(":", 1)
        m[k] = int(v.split()[0]) * 1024
    return {
        "total": m["MemTotal"],
        "available": m["MemAvailable"],
        "used": m["MemTotal"] - m["MemAvailable"],
        "cached": m.get("Cached", 0) + m.get("Buffers", 0),
    }


def swaps():
    out = []
    for line in read("/proc/swaps").splitlines()[1:]:
        name, kind, size, used, prio = line.split()[:5]
        entry = {"name": name, "size": int(size) * 1024, "used": int(used) * 1024,
                 "priority": int(prio), "role": "swap"}
        if name.startswith("/dev/zram"):
            entry["role"] = "zram"
            dev = os.path.basename(name)
            mm = safe(lambda: read("/sys/block/%s/mm_stat" % dev).split())
            if mm:
                entry["orig_data"], entry["compressed"] = int(mm[0]), int(mm[1])
        out.append(entry)
    # /swap is only enabled by ec2-hibinit-agent while hibernating
    if os.path.exists("/swap") and not any(s["name"] == "/swap" for s in out):
        out.append({"name": "/swap", "size": os.path.getsize("/swap"), "used": 0,
                    "priority": None, "role": "hibernation image (off at runtime)"})
    return out


def disks():
    out, seen = [], set()
    for line in read("/proc/mounts").splitlines():
        dev, mnt, fstype = line.split()[:3]
        if fstype not in REAL_FS or dev in seen:
            continue
        seen.add(dev)
        mnt = mnt.replace("\\040", " ")
        st = os.statvfs(mnt)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        out.append({"mount": mnt, "device": dev, "fstype": fstype,
                    "total": total, "used": total - st.f_bfree * st.f_frsize, "free": free})
    return out


def net_bytes():
    out = {}
    for line in read("/proc/net/dev").splitlines()[2:]:
        name, rest = line.split(":", 1)
        name = name.strip()
        if name == "lo":
            continue
        vals = rest.split()
        out[name] = (int(vals[0]), int(vals[8]))
    return out


def uptime():
    return float(read("/proc/uptime").split()[0])


def slept_seconds():
    """Time spent suspended/hibernated since boot (BOOTTIME counts it, MONOTONIC doesn't)."""
    return max(0.0, time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC))


# ---- processes ----------------------------------------------------------------

_users = {}


def username(uid):
    if uid not in _users:
        try:
            _users[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _users[uid] = str(uid)
    return _users[uid]


def read_proc(pid):
    stat = read("/proc/%s/stat" % pid)
    # comm may contain spaces and parens; fields resume after the last ')'
    lp, rp = stat.index("("), stat.rindex(")")
    comm = stat[lp + 1:rp]
    f = stat[rp + 2:].split()
    ticks = int(f[11]) + int(f[12])  # utime + stime
    start = int(f[19]) / CLK_TCK
    rss = int(f[21]) * PAGE_SIZE
    uid = os.stat("/proc/%s" % pid).st_uid
    try:
        cmd = read("/proc/%s/cmdline" % pid).replace("\0", " ").strip()
    except OSError:
        cmd = ""
    return {"pid": int(pid), "comm": comm, "ticks": ticks, "start": start, "rss": rss,
            "user": username(uid), "cmd": (cmd or "[%s]" % comm)[:160]}


def start_ticks(p):
    """Process start time in clock ticks since boot: with the pid, identifies
    one process even after the pid is reused."""
    return round(p["start"] * CLK_TCK)


def processes():
    procs = {}
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            p = safe(read_proc, pid)
            if p:
                procs[p["pid"]] = p
    return procs


# ---- listening ports ----------------------------------------------------------

def _addr(hexaddr, v6):
    ip, port = hexaddr.split(":")
    raw = bytes.fromhex(ip)
    if v6:  # four little-endian 32-bit words
        raw = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
        return socket.inet_ntop(socket.AF_INET6, raw), int(port, 16)
    return socket.inet_ntop(socket.AF_INET, raw[::-1]), int(port, 16)


def listening(procs):
    socks = []
    for path, v6 in (("/proc/net/tcp", False), ("/proc/net/tcp6", True)):
        for line in (safe(read, path) or "").splitlines()[1:]:
            f = line.split()
            if f[3] != "0A":  # LISTEN
                continue
            ip, port = _addr(f[1], v6)
            socks.append({"addr": ip, "port": port, "inode": f[9]})
    wanted = {s["inode"] for s in socks}
    owner = {}
    # Only processes we may inspect (our own, or all when run as root)
    for pid in procs:
        try:
            fds = os.listdir("/proc/%d/fd" % pid)
        except OSError:
            continue
        for fd in fds:
            try:
                link = os.readlink("/proc/%d/fd/%s" % (pid, fd))
            except OSError:
                continue
            if link.startswith("socket:["):
                ino = link[8:-1]
                if ino in wanted and ino not in owner:
                    owner[ino] = pid
    out, seen = [], set()
    for s in sorted(socks, key=lambda s: s["port"]):
        key = (s["addr"], s["port"])
        if key in seen:
            continue
        seen.add(key)
        pid = owner.get(s["inode"])
        p = procs.get(pid) if pid else None
        out.append({"addr": s["addr"], "port": s["port"], "pid": pid,
                    "user": p["user"] if p else None, "cmd": p["cmd"] if p else None,
                    "start": start_ticks(p) if p else None})
    return out


# ---- auto-hibernate -----------------------------------------------------------

_DUR = re.compile(r"([\d.]+)\s*(us|ms|s|min|h|d|w|month|y)\b")
_DUR_UNITS = {"us": 1e-6, "ms": 1e-3, "s": 1, "min": 60, "h": 3600, "d": 86400,
              "w": 604800, "month": 2629800, "y": 31557600}


def parse_duration(text):
    """systemd timespan ('42min 39.35s') -> seconds, or None."""
    parts = _DUR.findall(text)
    return sum(float(n) * _DUR_UNITS[u] for n, u in parts) if parts else None


def next_idle_check():
    out = subprocess.run(["systemctl", "show", "devbox-idle.timer", "-p", "NextElapseUSecMonotonic",
                          "--value"], capture_output=True, text=True, timeout=2).stdout
    mono = parse_duration(out)
    if mono is None:
        return None
    return time.time() + mono - time.clock_gettime(time.CLOCK_MONOTONIC)


def idle_conf():
    conf = {"IDLE_MINUTES": 30, "IDLE_HIBERNATE": "on"}
    for line in (safe(read, IDLE_CONF) or "").splitlines():
        m = re.match(r"\s*(IDLE_\w+)=(\S*)", line)
        if m:
            conf[m.group(1)] = m.group(2).strip("\"'")
    return conf


def tail(path, n):
    """Last n lines of a file without reading all of it."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        end = pos = f.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= n:
            pos = max(0, pos - 65536)
            f.seek(pos)
            data = f.read(end - pos)
    return data.decode(errors="replace").splitlines()[-n:]


def parse_log_line(line):
    ts, _, msg = line.partition(" ")
    try:
        t = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None, line
    return t, msg


def idle_state():
    if not os.path.exists(IDLE_CHECK):
        return None
    conf = idle_conf()
    minutes = int(conf["IDLE_MINUTES"])
    needed = -(-minutes // IDLE_INTERVAL_MIN)
    count = int((safe(read, IDLE_COUNT) or "0").strip() or 0)
    next_check = safe(next_idle_check)

    heartbeat = None
    for name in safe(os.listdir, HEARTBEAT_DIR) or []:
        mtime = safe(os.path.getmtime, os.path.join(HEARTBEAT_DIR, name))
        if mtime and (heartbeat is None or mtime > heartbeat):
            heartbeat = mtime

    last_status = last_hibernate = awake_since = None
    week = 0
    lines = safe(tail, IDLE_LOG, 5000)
    week_ago = time.time() - 7 * 86400
    for line in lines or []:
        t, msg = parse_log_line(line)
        if t is None:
            continue
        if msg.endswith("hibernating"):
            last_hibernate, awake_since = t, None
            if t >= week_ago:
                week += 1
        else:
            if last_hibernate and awake_since is None:
                awake_since = t  # first check after resume: within 5 min of waking
            last_status = {"time": t, "message": msg}

    hibernate_at = None
    if conf["IDLE_HIBERNATE"] == "on" and next_check:
        hibernate_at = next_check + max(0, needed - count - 1) * IDLE_INTERVAL_MIN * 60

    return {
        "enabled": conf["IDLE_HIBERNATE"] == "on",
        "idle_minutes": minutes,
        "count": count,
        "needed": needed,
        "next_check": next_check,
        "hibernate_at": hibernate_at,
        "heartbeat": heartbeat,
        "load_busy": NPROC * 0.25,
        "last_status": last_status,
        "last_hibernate": last_hibernate,
        "awake_since_estimate": awake_since,
        "hibernations_7d": week,
        "log_available": lines is not None,
        "log_path": IDLE_LOG,
    }


# ---- Claude Code sessions -----------------------------------------------------
# Each running `claude` keeps ~/.claude/sessions/<pid>.json up to date (the same
# registry `claude agents` lists): cwd, name, tmux pane and a status of busy /
# waiting (for you: permission prompt, question) / idle. These are internal
# formats, so every field is optional and anything unexpected is skipped.

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".claude")
TRANSCRIPT_TAIL = 1 << 20
STOPPED_KEEP = 86400
_transcripts = {}  # path -> (mtime, size, summary)


def _plain(text):
    """Markdown reply -> one line of plain text."""
    text = re.sub(r"\*\*|__|`|^#+\s*", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def _tool_summary(block):
    inp = block.get("input") or {}
    for key in ("description", "command", "file_path", "path", "pattern", "url", "query", "prompt"):
        v = inp.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().splitlines()[0][:140]
    return ""


def transcript_summary(path):
    """Title, last prompt and latest action from the end of a session transcript."""
    st = os.stat(path)
    cached = _transcripts.get(path)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return cached[2]
    with open(path, "rb") as f:
        f.seek(max(0, st.st_size - TRANSCRIPT_TAIL))
        lines = f.read().split(b"\n")
    if st.st_size > TRANSCRIPT_TAIL:
        lines = lines[1:]  # first line is probably cut off
    want = ("title", "custom_title", "prompt", "mode", "branch", "action", "reply", "reply_time", "last_activity", "recap", "recap_time")
    out = {}
    for raw in reversed(lines):
        if len(out) == len(want):
            break
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        kind = d.get("type")
        if kind == "ai-title" and "title" not in out:
            out["title"] = d.get("aiTitle")
        elif kind == "custom-title" and "custom_title" not in out:
            out["custom_title"] = d.get("customTitle")  # set by /rename
        elif kind == "last-prompt" and "prompt" not in out:
            out["prompt"] = (d.get("lastPrompt") or "")[:300]
        elif kind == "permission-mode" and "mode" not in out:
            out["mode"] = d.get("permissionMode")
        elif kind == "system" and d.get("subtype") == "away_summary" and "recap" not in out:
            # The recap Claude Code shows when you come back to a session
            text = d.get("content") if isinstance(d.get("content"), str) else ""
            out["recap"] = _plain(text.replace("(disable recaps in /config)", ""))[:500]
            out["recap_time"] = d.get("timestamp")
        if "branch" not in out and d.get("gitBranch"):
            out["branch"] = d["gitBranch"]
        if kind not in ("user", "assistant") or d.get("isSidechain"):
            continue
        if "last_activity" not in out and d.get("timestamp"):
            out["last_activity"] = d["timestamp"]
        content = (d.get("message") or {}).get("content")
        if kind != "assistant" or not isinstance(content, list):
            continue
        # Blocks of one turn are split across entries (thinking, text, tool_use).
        # Only the newest tool call or text counts as the current action.
        for block in reversed(content):
            if block.get("type") == "tool_use" and "action" not in out:
                out["action"] = {"tool": block.get("name"), "detail": _tool_summary(block)}
            elif block.get("type") == "text" and block.get("text", "").strip():
                out.setdefault("action", None)  # a reply after the last tool call supersedes it
                if "reply" not in out:
                    out["reply"], out["reply_time"] = _plain(block["text"])[:300], d.get("timestamp")
    _transcripts[path] = (st.st_mtime, st.st_size, out)
    return out


_first_prompts = {}  # path -> first prompt; it never changes


def first_prompt(path):
    """The first thing the user typed in a session (skips slash-command wrappers)."""
    if path in _first_prompts:
        return _first_prompts[path]
    found = None
    with open(path, "rb") as f:
        for n, raw in enumerate(f):
            if n > 5000:
                break
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
                continue
            content = (d.get("message") or {}).get("content")
            if isinstance(content, list):
                content = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
            text = _plain(content or "") if isinstance(content, str) else ""
            if text and not text.startswith("<"):
                found = text[:300]
                break
    _first_prompts[path] = found
    return found


def find_transcript(session_id):
    for proj in safe(os.listdir, os.path.join(CLAUDE_DIR, "projects")) or []:
        path = os.path.join(CLAUDE_DIR, "projects", proj, session_id + ".jsonl")
        if os.path.exists(path):
            return path
    return None


def git_branch(cwd):
    d = cwd
    while d and d != "/":
        head = os.path.join(d, ".git", "HEAD")
        if os.path.exists(head):
            ref = read(head).strip()
            return ref[16:] if ref.startswith("ref: refs/heads/") else ref[:12]
        d = os.path.dirname(d)
    return None


def claude_sessions(procs, rows):
    sess_dir = os.path.join(CLAUDE_DIR, "sessions")
    names = os.listdir(sess_dir)
    by_pid = {r["pid"]: r for r in rows}
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        s = safe(lambda: json.loads(read(os.path.join(sess_dir, name))))
        if not isinstance(s, dict) or not isinstance(s.get("pid"), int):
            continue
        pid = s["pid"]
        # Files outlive crashed or killed sessions, and pids get reused: a
        # session is live only if the recorded process start time matches.
        # Dead ones show as stopped for a day, then drop off.
        p = procs.get(pid)
        alive = p and (not s.get("procStart") or str(start_ticks(p)) == str(s["procStart"]))
        if not alive:
            if time.time() - (s.get("updatedAt") or 0) / 1000 > STOPPED_KEEP:
                continue
            s["status"], p = "stopped", None
        cwd = s.get("cwd") or (safe(os.readlink, "/proc/%d/cwd" % pid) if p else None)
        transcript = find_transcript(s["sessionId"]) if s.get("sessionId") else None
        summary = (safe(transcript_summary, transcript) if transcript else None) or {}
        row = by_pid.get(pid, {}) if p else {}
        # Title precedence: a /rename, then the generated title, then the
        # opening prompt. The generated title sometimes gets replaced by the
        # session's auto-name, which says less than the prompt.
        if s.get("nameSource") in ("user", "peer") and s.get("name"):
            title = s["name"]
        elif summary.get("custom_title"):
            title = summary["custom_title"]
        else:
            title = summary.get("title")
            if not title or title == s.get("name"):
                title = (safe(first_prompt, transcript) if transcript else None) or title
        out.append({
            "pid": pid,
            "session_id": s.get("sessionId"),
            "name": s.get("name"),
            "title": title,
            "cwd": cwd,
            "branch": safe(git_branch, cwd) if cwd else summary.get("branch"),
            "status": s.get("status") or "unknown",
            "waiting_for": s.get("waitingFor"),
            "status_since": (s.get("statusUpdatedAt") or s.get("updatedAt") or 0) / 1000 or None,
            "started": (s.get("startedAt") or 0) / 1000 or None,
            "kind": s.get("kind"),
            "tmux": s.get("tmux"),
            "version": s.get("version"),
            "mode": summary.get("mode"),
            "prompt": summary.get("prompt"),
            "action": summary.get("action"),
            "reply": summary.get("reply"),
            "reply_time": summary.get("reply_time"),
            "recap": summary.get("recap"),
            "recap_time": summary.get("recap_time"),
            "last_activity": summary.get("last_activity"),
            "cpu": row.get("cpu"),
            "rss": row.get("rss"),
            "start": row.get("start"),
        })
    order = {"waiting": 0, "busy": 1, "idle": 2, "shell": 2, "stopped": 4}
    out.sort(key=lambda s: (order.get(s["status"], 3), -(s["status_since"] or 0)))
    return out


# ---- instance metadata --------------------------------------------------------

def imds():
    base = "http://169.254.169.254/latest"
    req = urllib.request.Request(base + "/api/token", method="PUT",
                                 headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
    token = urllib.request.urlopen(req, timeout=1).read().decode()

    def md(path):
        r = urllib.request.Request(base + "/meta-data/" + path,
                                   headers={"X-aws-ec2-metadata-token": token})
        return urllib.request.urlopen(r, timeout=1).read().decode()

    return {k: safe(md, p) for k, p in (("instance_id", "instance-id"),
                                         ("instance_type", "instance-type"),
                                         ("region", "placement/region"),
                                         ("name", "tags/instance/Name"))}


# ---- sampler ------------------------------------------------------------------

class Sampler:
    """Samples every SAMPLE_SEC so requests only read the cached snapshot."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sampling = threading.Lock()  # sample() runs from the loop and after a stop
        self.history = collections.deque(maxlen=HISTORY)
        self.snapshot = {}
        self.instance = None
        self._prev = None

    def start(self):
        threading.Thread(target=self._imds, daemon=True).start()
        threading.Thread(target=self._loop, daemon=True).start()

    def _imds(self):
        self.instance = safe(imds)

    def _loop(self):
        while True:
            time.sleep(SAMPLE_SEC)
            try:
                self.sample()
            except Exception as e:  # keep sampling; surface the error on the page
                with self.lock:
                    self.snapshot["error"] = repr(e)

    def sample(self):
        with self.sampling:
            self._sample()

    def resample_soon(self):
        """Refresh right after a stop so the page drops the row on its next poll."""
        threading.Timer(0.5, lambda: safe(self.sample)).start()

    def _sample(self):
        now = time.time()
        cpu = cpu_times()
        net = safe(net_bytes) or {}
        procs = processes()
        prev = self._prev
        # A gap much longer than the interval means we were hibernated: rates
        # across it are meaningless, so treat this sample as the first.
        if prev and now - prev["time"] > SAMPLE_SEC * 6:
            prev = None
        dt = now - prev["time"] if prev else None

        def pct(name):
            if not prev or name not in prev["cpu"]:
                return None
            busy = cpu[name][0] - prev["cpu"][name][0]
            total = cpu[name][1] - prev["cpu"][name][1]
            return round(100.0 * busy / total, 1) if total > 0 else 0.0

        cpu_pct = pct("cpu")
        cores = [pct("cpu%d" % i) for i in range(len(cpu) - 1)]

        rates = {}
        if prev:
            for name, (rx, tx) in net.items():
                if name in prev["net"]:
                    p_rx, p_tx = prev["net"][name]
                    rates[name] = {"rx": max(0, rx - p_rx) / dt, "tx": max(0, tx - p_tx) / dt}
        rx_total = sum(r["rx"] for r in rates.values()) if rates else None
        tx_total = sum(r["tx"] for r in rates.values()) if rates else None

        up = uptime()
        rows = []
        for pid, p in procs.items():
            cpu_p = None
            if prev and pid in prev["ticks"]:
                cpu_p = round(100.0 * (p["ticks"] - prev["ticks"][pid]) / CLK_TCK / dt, 1)
            rows.append({"pid": pid, "user": p["user"], "cpu": cpu_p, "rss": p["rss"],
                         "age": max(0, up - p["start"]), "start": start_ticks(p),
                         "cmd": p["cmd"], "comm": p["comm"]})
        top_cpu = sorted((r for r in rows if r["cpu"]), key=lambda r: -r["cpu"])[:TOP_N]
        top_mem = sorted(rows, key=lambda r: -r["rss"])[:TOP_N]

        mem = meminfo()
        sw = safe(swaps) or []
        swap_used = sum(s["used"] for s in sw)
        load = [float(x) for x in read("/proc/loadavg").split()[:3]]

        self._prev = {"time": now, "cpu": cpu, "net": net,
                      "ticks": {pid: p["ticks"] for pid, p in procs.items()}}

        snap = {
            "time": now,
            "host": {"hostname": socket.gethostname(), "kernel": os.uname().release,
                     "arch": os.uname().machine, "nproc": NPROC, "uptime": up,
                     "boot_time": now - up, "slept": safe(slept_seconds),
                     "instance": self.instance, "user": ME, "pid": os.getpid()},
            "cpu": {"percent": cpu_pct, "cores": cores, "load": load},
            "memory": mem,
            "swap": sw,
            "disks": safe(disks),
            "network": {"interfaces": rates, "rx": rx_total, "tx": tx_total},
            "processes": {"count": len(procs), "top_cpu": top_cpu, "top_mem": top_mem},
            "ports": safe(listening, procs),
            "idle": safe(idle_state),
            "claude": safe(claude_sessions, procs, rows),
        }
        with self.lock:
            if cpu_pct is not None:
                self.history.append([round(now), cpu_pct, load[0],
                                     round(100.0 * mem["used"] / mem["total"], 1),
                                     swap_used, rx_total, tx_total])
            snap["history"] = {"fields": ["time", "cpu", "load1", "mem_pct", "swap_used", "rx", "tx"],
                               "rows": list(self.history)}
            self.snapshot = snap

    def get(self):
        with self.lock:
            return self.snapshot


# ---- stopping processes -------------------------------------------------------
# POST /api/stop sends SIGTERM to one of this user's processes. The kernel
# already limits us to our own user's processes; the checks below make sure
# the request comes from this dashboard's own page and not from another site
# open in the same browser.

ME = pwd.getpwuid(os.getuid()).pw_name


def local_addresses():
    out = subprocess.run(["ip", "-o", "addr", "show"], capture_output=True, text=True, timeout=2).stdout
    return {line.split()[3].split("/")[0] for line in out.splitlines() if len(line.split()) > 3}


def allowed_host(host, instance_name):
    """Host header check against DNS rebinding: a site whose name resolves to
    this box still sends its own name, which isn't one of ours."""
    host = host.lower()
    if host.startswith("["):  # [ipv6]:port
        host = host[1:host.find("]")]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    names = {socket.gethostname().lower(), socket.gethostname().split(".")[0].lower()}
    if instance_name:
        names.add(instance_name.lower())
    names.update(h.strip().lower() for h in os.environ.get("DASHBOARD_HOSTS", "").split(",") if h.strip())
    # Bare names, and Tailscale MagicDNS names (<name>.<tailnet>.ts.net)
    if host in names or (host.split(".")[0] in names and host.endswith(".ts.net")):
        return True
    return host in (safe(local_addresses) or set())


def stop_process(pid, start):
    if pid <= 1 or pid == os.getpid():
        return 403, "refusing to stop that process"
    p = safe(read_proc, str(pid))
    if not p or start_ticks(p) != start:
        return 409, "process already exited (or its pid was reused)"
    if p["user"] != ME:
        return 403, "owned by %s; the dashboard runs as %s" % (p["user"], ME)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        return 500, str(e)
    print("stopped pid %d (%s) via dashboard" % (pid, p["cmd"][:120]), flush=True)
    return 200, "sent SIGTERM to pid %d" % pid


# ---- hibernate ----------------------------------------------------------------
# Same call the idle checker makes, through the instance role (which only
# allows stopping instances tagged Name=devbox). The decision goes into the
# idle checker's log first, so the dashboard's hibernation metrics count it.

def hibernate(instance, dry_run=False):
    if not instance or not instance.get("instance_id") or not instance.get("region"):
        return 503, "not on EC2 (no instance metadata)"
    if not os.access(IDLE_LOG, os.W_OK):
        return 500, ("can't write %s, so the hibernation wouldn't be logged. Fix (ssm): "
                     "sudo chgrp %s %s && sudo chmod 664 %s" % (IDLE_LOG, ME, IDLE_LOG, IDLE_LOG))
    cmd = ["aws", "ec2", "stop-instances", "--hibernate", "--region", instance["region"],
           "--instance-ids", instance["instance_id"]] + (["--dry-run"] if dry_run else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 500, "aws cli failed: %s" % e
    out = (r.stderr or r.stdout).strip()
    if dry_run:
        # EC2 answers a permitted dry run with a DryRunOperation "error"
        return (200, "dry run ok: the instance role may hibernate this box") if "DryRunOperation" in out \
            else (500, "dry run failed: " + out[-300:])
    if r.returncode != 0:
        return 500, "aws ec2 stop-instances failed: " + out[-300:]
    # Logged only once EC2 has accepted the request; the box keeps running
    # for several seconds after this. Same ending as the checker's line, so
    # the dashboard counts it as a hibernation.
    msg = "dashboard request, hibernating"
    subprocess.run(["logger", "-t", "devbox-idle", msg], timeout=5)
    with open(IDLE_LOG, "a") as f:
        f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg))
    os.sync()
    print("hibernate requested via dashboard", flush=True)
    return 200, "hibernating"


# ---- http ---------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    sampler = None

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj):
        self.send(200, json.dumps(obj, separators=(",", ":")).encode(), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self.send(200, f.read(), "text/html; charset=utf-8")
        elif url.path == "/api/stats":
            self.json(self.sampler.get())
        elif url.path == "/api/log":
            n = int(parse_qs(url.query).get("n", ["100"])[0])
            lines = safe(tail, IDLE_LOG, max(1, min(n, 2000)))
            self.json({"path": IDLE_LOG, "available": lines is not None, "lines": lines or []})
        else:
            self.send(404, b"not found\n", "text/plain")

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/stop", "/api/hibernate"):
            return self.send(404, b"not found\n", "text/plain")
        refused = self.refuse_foreign()
        if refused:
            return self.reply(403, refused)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(length, 4096)) or b"{}")
        except ValueError:
            return self.reply(400, "expected a JSON body")
        if path == "/api/hibernate":
            return self.reply(*hibernate(self.sampler.instance, dry_run=body.get("dry_run") is True))
        try:
            pid, start = int(body["pid"]), int(body["start"])
        except (KeyError, TypeError, ValueError):
            return self.reply(400, "expected JSON {pid, start}")
        code, message = stop_process(pid, start)
        if code == 200:
            self.sampler.resample_soon()
        self.reply(code, message)

    def refuse_foreign(self):
        """Reason to refuse a request that didn't come from this dashboard's
        own page, or None. A custom header can't be sent cross-origin without
        a CORS preflight, which this server never approves; Origin and Host
        catch the rest, including DNS rebinding."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if self.headers.get("X-Dashboard") != "1":
            return "missing X-Dashboard header"
        if not origin or urlparse(origin).netloc != host:
            return "cross-origin request refused"
        if not allowed_host(host, (self.sampler.instance or {}).get("name")):
            return "unknown Host %r (add it to DASHBOARD_HOSTS)" % host
        return None

    def reply(self, code, message):
        body = json.dumps({"ok": code == 200, "message": message}).encode()
        self.send(code, body, "application/json")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bind", default=os.environ.get("DASHBOARD_BIND", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", "9999")))
    args = ap.parse_args()

    Handler.sampler = Sampler()
    Handler.sampler.sample()  # prime deltas so the first page load has data soon
    Handler.sampler.start()
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    print("devbox dashboard on http://%s:%d" % (args.bind, args.port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
