#!/usr/bin/env python3
"""devbox dashboard: processes, resources, auto-hibernate and agent-runner state.

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
PAUSE_FILE = os.path.join(HEARTBEAT_DIR, "paused")  # exists while auto-hibernate is paused
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


# What takes up the disk: one `du` pass over the home directory, run only when
# the disk modal asks for it (it reads every inode, far too slow for the
# sampler) and kept for a minute so reopening the modal doesn't repeat it.

HOME = pwd.getpwuid(os.getuid()).pw_dir
DU_DEPTH = 3       # how far below HOME a directory is split into its entries
DU_TOP = 30
DU_TIMEOUT = 120
DU_TTL = 60
_du = {"lock": threading.Lock(), "result": None}


def du_scan(root):
    """Largest entries under root. Directories are split into their entries
    down to DU_DEPTH, except git checkouts and worktrees, which stay whole: one
    row per worktree says more than its node_modules and .git separately."""
    r = subprocess.run(["nice", "-n", "19", "du", "-x", "-a", "-k", "-0", "--max-depth=%d" % DU_DEPTH, root],
                       capture_output=True, timeout=DU_TIMEOUT)  # exits 1 on unreadable dirs; the rest still counts
    sizes, children = {}, collections.defaultdict(list)
    for rec in r.stdout.split(b"\0"):
        kb, _, path = rec.decode(errors="replace").partition("\t")
        if path and kb.isdigit():
            sizes[path] = int(kb) * 1024
            children[os.path.dirname(path)].append(path)
    if root not in sizes:
        raise RuntimeError((r.stderr.decode(errors="replace").strip().splitlines() or ["du printed nothing"])[-1][:200])
    items, todo = [], [root]
    while todo:
        path = todo.pop()
        git = os.path.join(path, ".git")
        if path in children and not os.path.lexists(git):
            todo.extend(children[path])
            continue
        kind = "file"
        if os.path.isdir(path) and not os.path.islink(path):
            kind = "worktree" if os.path.isfile(git) else "repo" if os.path.isdir(git) else "dir"
        items.append({"path": path, "size": sizes[path], "kind": kind})
    items.sort(key=lambda i: -i["size"])
    return sizes[root], items[:DU_TOP]


def disk_usage(refresh=False):
    asked = time.time()
    with _du["lock"]:  # one scan at a time; whoever waited gets its result
        res = _du["result"]
        if res and (res["time"] >= asked or (not refresh and asked - res["time"] < DU_TTL)):
            return res
        start = time.time()
        res = {"root": HOME, "total": None, "items": [], "other": None, "error": None}
        try:
            res["total"], res["items"] = du_scan(HOME)
        except subprocess.TimeoutExpired:
            res["error"] = "du took longer than %d s" % DU_TIMEOUT
        except Exception as e:
            res["error"] = str(e) or repr(e)
        # The rest of HOME's filesystem: system files, other users
        mounts = [d for d in safe(disks) or [] if os.path.commonpath([HOME, d["mount"]]) == d["mount"]]
        if mounts and res["total"] is not None:
            d = max(mounts, key=lambda d: len(d["mount"]))
            res["other"] = {"mount": d["mount"], "size": max(0, d["used"] - res["total"])}
        res["time"] = time.time()
        res["took"] = res["time"] - start
        _du["result"] = res
        return res


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
    conf = {"IDLE_MINUTES": 60, "IDLE_HIBERNATE": "on"}
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
        if name == os.path.basename(PAUSE_FILE):
            continue
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

    paused = os.path.exists(PAUSE_FILE)
    hibernate_at = None
    if conf["IDLE_HIBERNATE"] == "on" and not paused and next_check:
        hibernate_at = next_check + max(0, needed - count - 1) * IDLE_INTERVAL_MIN * 60

    return {
        "enabled": conf["IDLE_HIBERNATE"] == "on",
        "paused": paused,
        # Checkers installed before the pause flag existed would ignore it
        "pause_supported": "PAUSE_FILE" in (safe(read, IDLE_CHECK) or ""),
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


# Live log: the session modal polls with the byte offset it has read up to and
# gets back only whole lines appended since. Claude Code writes one transcript
# line per finished content block (text, tool call, tool result), so this
# follows the session block by block, not token by token.

LOG_FIRST = 256 << 10  # first open: the tail of the transcript
LOG_STEP = 1 << 20     # most read per poll
LOG_TEXT = 4000        # longest text or tool result sent
SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _result_text(content):
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") if b.get("type") == "text" else "[%s]" % b.get("type")
                            for b in content if isinstance(b, dict))
    return content if isinstance(content, str) else ""


def log_events(d):
    """Transcript line -> events the modal shows. Bookkeeping lines
    (attachments, titles, hooks) and subagent sidechains are skipped."""
    kind = d.get("type")
    if kind not in ("user", "assistant") or d.get("isSidechain"):
        return []
    t = d.get("timestamp")
    content = (d.get("message") or {}).get("content")
    if isinstance(content, str):
        if kind == "user" and not d.get("isMeta") and content.strip() and not content.startswith("<"):
            return [{"t": t, "kind": "user", "text": content[:LOG_TEXT]}]
        return []
    out = []
    for b in content if isinstance(content, list) else []:
        bt = b.get("type") if isinstance(b, dict) else None
        if bt == "text" and b.get("text", "").strip():
            text = b["text"]
            if kind == "user" and (d.get("isMeta") or text.startswith("<")):
                continue
            out.append({"t": t, "kind": "text" if kind == "assistant" else "user", "text": text[:LOG_TEXT]})
        elif bt == "tool_use":
            cmd = (b.get("input") or {}).get("command")
            out.append({"t": t, "kind": "tool", "tool": b.get("name"), "text": _tool_summary(b),
                        "cmd": cmd[:LOG_TEXT] if isinstance(cmd, str) else None})
        elif bt == "tool_result":
            text = _result_text(b.get("content"))
            out.append({"t": t, "kind": "result", "error": bool(b.get("is_error")),
                        "text": text[:LOG_TEXT], "cut": len(text) > LOG_TEXT})
        elif bt == "thinking":
            out.append({"t": t, "kind": "thinking", "text": (b.get("thinking") or "")[:LOG_TEXT]})
    return out


def session_log(session_id, offset):
    """New events in a session's transcript since byte offset (-1: its tail)."""
    path = find_transcript(session_id)
    if not path:
        return None
    size = os.path.getsize(path)
    if offset < 0 or offset > size:  # first poll, or the file was replaced
        offset = max(0, size - LOG_FIRST)
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(LOG_STEP)
    if offset and not (offset == size or data.startswith(b"{")):
        cut = data.find(b"\n") + 1  # landed mid-line: skip to the next one
        offset, data = offset + cut, data[cut:] if cut else b""
    end = data.rfind(b"\n") + 1  # a partly written last line waits for the next poll
    if not end and len(data) == LOG_STEP:
        end = len(data)  # one line longer than LOG_STEP: skip it rather than stall
    events = []
    for raw in data[:end].split(b"\n"):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict):
            events.extend(log_events(d))
    return {"offset": offset + end, "size": size, "more": offset + end < size, "events": events}


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


# ---- agent runner -------------------------------------------------------------
# agent-runner (../../agent-runner) keeps its state in ~/.agent-runner: a lock
# held while a run is in progress, cron.log, one JSON log per issue run
# (<repo>-<N>-<YYYYmmdd-HHMMSS>.json, empty until the run ends) and a worktree
# per open issue. The run's Claude session is also in the Agent sessions card;
# here it's matched by cwd to show what the current run is doing.

RUNNER_HOME = os.environ.get("AGENT_RUNNER_HOME") or os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".agent-runner")
RUNNER_RUNS = 10
RUNNER_LOG_LINES = 80
RUNNER_CONF_TTL = 60
RUN_RAW_MAX = 512 * 1024
_runner_runs = {}  # log path -> (mtime, size, run)
_runner_titles = {}  # session id -> title; it never changes
_runner_conf = {"time": 0}


def lock_holder(path):
    """Pid holding a flock on path (as /proc/locks reports it), or None. Reads
    /proc/locks instead of trying the lock, which could make a cron tick skip."""
    st = os.stat(path)
    key = "%02x:%02x:%d" % (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    for line in read("/proc/locks").splitlines():
        f = line.split()
        if "->" not in f and len(f) > 5 and f[5] == key:  # "->" marks a blocked waiter
            return int(f[4])
    return None


_CRON_MACROS = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
                "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *",
                "@annually": "0 0 1 1 *"}


def cron_field(spec, lo, hi):
    vals = set()
    for part in spec.split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = (int(x) for x in rng.split("-"))
        else:
            a = b = int(rng)
            if step:
                b = hi
        vals.update(range(a, b + 1, int(step or 1)))
    return vals


def cron_next(expr, now):
    """Next time (local, as cron uses) a numeric 5-field schedule fires, or None."""
    f = _CRON_MACROS.get(expr, expr).split()
    mins, hours, dom, mon, dow = (cron_field(f[i], lo, hi) for i, (lo, hi) in
                                  enumerate(((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))))
    if 7 in dow:
        dow.add(0)
    t = (int(now) // 60 + 1) * 60
    for _ in range(8 * 24 * 60):
        tm = time.localtime(t)
        # When both day fields are restricted, cron fires on either
        day_dom, day_dow = tm.tm_mday in dom, (tm.tm_wday + 1) % 7 in dow
        if f[2] != "*" and f[4] != "*":
            day = day_dom or day_dow
        else:
            day = day_dom and day_dow
        if tm.tm_min in mins and tm.tm_hour in hours and tm.tm_mon in mon and day:
            return t
        t += 60
    return None


def runner_conf():
    """Cron entry and repo slugs; they rarely change, so read once a minute. The
    entry comes from the copy agent-runner/install.sh leaves in RUNNER_HOME, not
    `crontab -l`: the service's NoNewPrivileges stops the setuid crontab binary
    from reading the spool, and it fails the PAM check."""
    if time.time() - _runner_conf["time"] < RUNNER_CONF_TTL:
        return _runner_conf
    schedule = path = None
    crontab = safe(read, os.path.join(RUNNER_HOME, "crontab"))
    for line in (crontab or "").splitlines():
        line = line.strip()
        if line.startswith("PATH="):
            path = line[5:]  # the one in effect for the entry below it
        elif "agent-runner" in line and not line.startswith("#"):
            f = line.split()
            n = 1 if f[0].startswith("@") else 5
            schedule = " ".join(f[:n])
            break
    # <checkout name> -> owner/repo, from each watched checkout's origin remote
    repos = {}
    for line in (safe(read, os.path.join(RUNNER_HOME, "repos")) or "").splitlines():
        f = line.split()
        if not f or f[0].startswith("#"):
            continue
        d = os.path.expanduser(f[0])
        url = safe(lambda: re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)',
                                     read(os.path.join(d, ".git", "config"))).group(1))
        m = url and re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
        if m:
            repos[os.path.basename(d.rstrip("/"))] = m.group(1)
    _runner_conf.update(time=time.time(), crontab=crontab is not None, schedule=schedule,
                        path=path, repos=repos)
    return _runner_conf


# Issue labels, as set by agent-runner; the first one present gives the state.
AGENT_LABELS = (("agent-wip", "wip"), ("agent", "queued"), ("agent-needs-human", "needs_human"),
                ("agent-failed", "failed"), ("agent-pr", "pr"))
GH_REFRESH = 60


def gh_json(args, path):
    env = dict(os.environ, PATH=path or os.environ.get("PATH", ""))
    try:
        r = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=20, env=env)
    except FileNotFoundError:
        raise RuntimeError("gh not found on PATH")
    if r.returncode:
        raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or ["gh exited %d" % r.returncode])[-1][:200])
    return json.loads(r.stdout)


def github_state(conf):
    """Open issues and agent PRs of each watched repo. Slow (network), so the
    sampler refreshes it once a minute in its own thread."""
    out = {"time": time.time(), "error": None, "repos": {}}
    for name, slug in conf["repos"].items():
        try:
            issues = gh_json(["issue", "list", "-R", slug, "--state", "open", "--limit", "200",
                              "--json", "number,title,url,labels,updatedAt"], conf["path"])
            prs = gh_json(["pr", "list", "-R", slug, "--state", "open", "--limit", "100",
                           "--json", "number,url,isDraft,headRefName,labels,reviews"], conf["path"])
        except Exception as e:
            out["error"] = "%s: %s" % (slug, e)
            continue
        seen = set((safe(read, os.path.join(RUNNER_HOME, "reviews-seen")) or "").splitlines())
        agent_prs = {}
        for p in prs:
            if p["headRefName"].startswith("agent/issue-"):
                p["trigger"] = pr_trigger(slug, p, seen)
                del p["labels"], p["reviews"]
                agent_prs[p["headRefName"]] = p
        out["repos"][name] = {"issues": issues, "prs": agent_prs}
    return out


def create_issue(conf, repo, title, body):
    """Files an issue labeled agent, so the runner's next tick picks it up."""
    slug = conf["repos"].get(repo)
    if not slug:
        return 400, "not a repo the runner watches: %r" % repo
    env = dict(os.environ, PATH=conf["path"] or os.environ.get("PATH", ""))
    try:
        r = subprocess.run(["gh", "issue", "create", "-R", slug, "--title", title, "--body", body,
                            "--label", "agent"], capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 500, "gh failed: %s" % e
    if r.returncode:
        return 500, "gh issue create failed: " + (r.stderr or r.stdout).strip()[-300:]
    url = (r.stdout.strip().splitlines() or [""])[-1]  # gh prints the new issue's URL last
    print("created %s via dashboard" % url, flush=True)
    return 200, url


def pr_trigger(slug, pr, seen):
    """Why the runner's next tick will pick this PR's issue up, if it will: the
    trigger label on the PR or a code review no run has been given yet (the same
    rules as pr_triggers in agent-runner)."""
    if any(lb.get("name") == "agent" for lb in pr.get("labels") or []):
        return "label"
    for r in pr.get("reviews") or []:
        if (r.get("authorAssociation") in ("OWNER", "MEMBER", "COLLABORATOR")
                and (r.get("state") in ("COMMENTED", "CHANGES_REQUESTED")
                     or (r.get("state") == "APPROVED" and r.get("body")))
                and "%s#%d %s" % (slug, pr["number"], r.get("id")) not in seen):
            return "review"
    return None


def session_title(session_id):
    """The --name the runner gave the session ("devbox#7 - title"), from the
    first lines of its transcript."""
    if session_id in _runner_titles:
        return _runner_titles[session_id]
    title = None
    path = find_transcript(session_id)
    if path:
        with open(path, "rb") as f:
            for n, raw in enumerate(f):
                if n > 50:
                    break
                d = safe(json.loads, raw) or {}
                if d.get("type") == "custom-title" and d.get("customTitle"):
                    title = d["customTitle"]
                    break
    _runner_titles[session_id] = title
    return title


def issue_title(name):
    # "Issue #7 - " from runners before sessions were named like the issues
    return re.sub(r"^(?:Issue |[\w.-]+)#\d+ - ", "", name) if name else None


def runner_run(path):
    st = os.stat(path)
    cached = _runner_runs.get(path)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return dict(cached[2])
    m = re.match(r"(.+)-(\d+)-(\d{8}-\d{6})\.json$", os.path.basename(path))
    if not m:
        return None
    run = {"repo": m.group(1), "issue": int(m.group(2)), "log": path,
           "started": time.mktime(time.strptime(m.group(3), "%Y%m%d-%H%M%S")),
           "ended": None, "status": "pending", "title": None, "summary": None}
    if st.st_size:
        run["ended"] = st.st_mtime
        try:
            d = json.loads(read(path))
        except ValueError:  # claude failed before printing its JSON
            d = {}
        out = d.get("structured_output") or {}
        run["status"] = out.get("status") or "failed"
        text = out.get("question") if run["status"] == "needs_human" else out.get("summary")
        if run["status"] == "failed" and not text:
            text = d.get("result") or safe(lambda: read(path)[:300])
        run["summary"] = _plain(text or "")[:400] or None
        run["cost"] = d.get("total_cost_usd")
        run["turns"] = d.get("num_turns")
        if d.get("duration_ms"):
            run["ended"] = run["started"] + d["duration_ms"] / 1000
        if d.get("session_id"):
            run["title"] = issue_title(safe(session_title, d["session_id"]))
    _runner_runs[path] = (st.st_mtime, st.st_size, run)
    return dict(run)


def runner_worktree(path):
    gitdir = read(os.path.join(path, ".git")).strip()[len("gitdir: "):]
    ref = read(os.path.join(gitdir, "HEAD")).strip()
    activity = max(safe(os.path.getmtime, os.path.join(gitdir, p)) or 0
                   for p in ("HEAD", "index", "logs/HEAD"))
    m = re.match(r"(.+)-(\d+)$", os.path.basename(path))
    return {"name": os.path.basename(path), "path": path,
            "repo": m.group(1) if m else None, "issue": int(m.group(2)) if m else None,
            "branch": ref[16:] if ref.startswith("ref: refs/heads/") else ref[:12],
            "activity": activity or None}


def open_issues(conf, github, worktrees, last_run):
    """Open issues the runner has touched (any agent-* label), with their PR,
    worktree and last run, plus worktrees whose issue no longer qualifies (they
    pile up if cleanup fails)."""
    github = github or {"repos": {}}
    wt_by = {(w["repo"], w["issue"]): w for w in worktrees}
    rows, seen = [], set()
    for name, data in github["repos"].items():
        for i in data["issues"]:
            labels = [{"name": lb.get("name"), "color": lb.get("color")} for lb in i.get("labels") or []]
            names = {lb["name"] for lb in labels}
            state = next((st for lb, st in AGENT_LABELS if lb in names), None)
            key = (name, i["number"])
            pr = data["prs"].get("agent/issue-%d" % i["number"])
            # Queued from the PR (its label or a new code review) rather than the issue
            queued_by = pr and pr.get("trigger")
            if queued_by and state != "wip":
                state = "queued"
            if not state and key not in wt_by:
                continue
            seen.add(key)
            rows.append({"repo": name, "issue": i["number"], "title": i.get("title"), "url": i.get("url"),
                         "labels": labels, "state": state, "updated": i.get("updatedAt"), "pr": pr,
                         "queued_by": queued_by if state == "queued" else None})
    for w in worktrees:
        key = (w["repo"], w["issue"])
        if key in seen:
            continue
        # Not among the open issues GitHub returned: closed (removed on the next
        # tick), or GitHub couldn't be reached for this repo.
        rows.append({"repo": w["repo"], "issue": w["issue"], "title": w["title"], "url": w["url"],
                     "labels": None, "state": "closed" if w["repo"] in github["repos"] else None,
                     "updated": None, "pr": None, "queued_by": None})
    order = {st: n for n, (_, st) in enumerate(AGENT_LABELS)}
    rows.sort(key=lambda r: r["updated"] or "", reverse=True)
    rows.sort(key=lambda r: order.get(r["state"], len(order)))
    for r in rows:
        w = wt_by.get((r["repo"], r["issue"]))
        r["worktree"] = {k: w[k] for k in ("name", "path", "branch", "activity")} if w else None
        run = last_run.get((r["repo"], r["issue"]))
        r["last_run"] = {k: run[k] for k in ("status", "started", "log")} if run else None
        r["title"] = r["title"] or (run and run["title"])
    return rows


def agent_runner(sessions, github):
    if not os.path.isdir(RUNNER_HOME):
        return None
    now = time.time()
    conf = runner_conf()
    lock = os.path.join(RUNNER_HOME, "lock")
    holder = safe(lock_holder, lock) if os.path.exists(lock) else None

    log_dir = os.path.join(RUNNER_HOME, "logs")
    paths = sorted((os.path.join(log_dir, n) for n in safe(os.listdir, log_dir) or [] if n.endswith(".json")),
                   key=lambda p: os.path.basename(p).rsplit("-", 2)[-2:], reverse=True)
    runs = [r for r in (safe(runner_run, p) for p in paths[:RUNNER_RUNS]) if r]
    wt_root = os.path.join(RUNNER_HOME, "worktrees")
    by_cwd = {s["cwd"]: s for s in sessions or [] if s.get("cwd")}
    current = None
    for r in runs:
        if r["status"] != "pending":
            continue
        # An empty log is the run in progress while the lock is held; one
        # left behind by an older run means that run was killed.
        if holder and current is None:
            r["status"], current = "running", r
            s = by_cwd.get(os.path.join(wt_root, "%s-%d" % (r["repo"], r["issue"])))
            if s:
                r["title"] = issue_title(s.get("name")) or s.get("title")
                r["session"] = {k: s.get(k) for k in ("pid", "status", "waiting_for", "action", "reply", "start")}
        else:
            r["status"] = "interrupted"
    # Runs that failed early have no session to take a title from; borrow one
    # from another run of the same issue.
    titles = {(r["repo"], r["issue"]): r["title"] for r in reversed(runs) if r["title"]}
    last_run = {}
    for r in runs:
        repo = conf["repos"].get(r["repo"])
        r["url"] = "https://github.com/%s/issues/%d" % (repo, r["issue"]) if repo else None
        r["title"] = r["title"] or titles.get((r["repo"], r["issue"]))
        last_run.setdefault((r["repo"], r["issue"]), r)

    worktrees = []
    for name in sorted(safe(os.listdir, wt_root) or []):
        w = safe(runner_worktree, os.path.join(wt_root, name))
        if w:
            repo = conf["repos"].get(w["repo"])
            w["url"] = "https://github.com/%s/issues/%d" % (repo, w["issue"]) if repo and w["issue"] else None
            r = last_run.get((w["repo"], w["issue"]))
            w["title"] = r["title"] if r else None
            worktrees.append(w)

    cron_log = os.path.join(RUNNER_HOME, "cron.log")
    lines = safe(tail, cron_log, RUNNER_LOG_LINES)
    last_tick = None
    for line in reversed(lines or []):
        m = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]", line)
        if m:
            last_tick = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            break

    return {
        "home": RUNNER_HOME,
        "running": holder is not None,
        "holder": holder,
        "current": current,
        "crontab": conf["crontab"],
        "schedule": conf["schedule"],
        "next_run": safe(cron_next, conf["schedule"], now) if conf["schedule"] else None,
        "last_log_line": last_tick,
        "runs": runs,
        "issues": open_issues(conf, github, worktrees, last_run),
        "repos": [{"name": n, "slug": s} for n, s in sorted(conf["repos"].items())],
        "worktrees": len(worktrees),
        "github": github and {"time": github["time"], "error": github["error"]},
        "log": {"path": cron_log, "available": lines is not None, "lines": lines or []},
    }


def run_details(name):
    """Everything in one run's log, plus its cron.log lines, for the run modal."""
    if not re.fullmatch(r"[\w.-]+\.json", name or ""):
        return None
    path = os.path.join(RUNNER_HOME, "logs", name)
    run = os.path.isfile(path) and runner_run(path)
    if not run:
        return None
    with open(path, "rb") as f:
        raw = f.read(RUN_RAW_MAX + 1).decode(errors="replace")
    d = safe(json.loads, raw) if len(raw) <= RUN_RAW_MAX else None
    d = d if isinstance(d, dict) else {}
    out = d.get("structured_output") or {}
    ended = run["ended"] or time.time()
    lines, t = [], None
    for line in safe(tail, os.path.join(RUNNER_HOME, "cron.log"), 5000) or []:
        m = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]", line)
        if m:
            t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
        if t and run["started"] - 60 <= t <= ended + 120:
            lines.append(line)
    return {
        "log": path,
        "size": os.path.getsize(path),
        "raw": raw[:RUN_RAW_MAX],
        "truncated": len(raw) > RUN_RAW_MAX,
        "status": out.get("status"),
        "summary": out.get("summary"),
        "decisions": out.get("decisions") or [],
        "question": out.get("question"),
        "result": None if out else d.get("result"),
        "is_error": d.get("is_error"),
        "session_id": d.get("session_id"),
        "models": sorted((d.get("modelUsage") or {}).keys()),
        "denials": [{"tool": x.get("tool_name"), "detail": _tool_summary({"input": x.get("tool_input")})}
                    for x in d.get("permission_denials") or [] if isinstance(x, dict)],
        "cron": lines,
    }


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
        self.github = None
        self.github_now = threading.Event()  # set to refresh from GitHub before the minute is up
        self._prev = None

    def start(self):
        threading.Thread(target=self._imds, daemon=True).start()
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._github, daemon=True).start()

    def _imds(self):
        self.instance = safe(imds)

    def _github(self):
        while True:
            if os.path.isdir(RUNNER_HOME):
                self.github = safe(github_state, runner_conf()) or self.github
                self.resample_soon()
            self.github_now.wait(GH_REFRESH)
            self.github_now.clear()

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
        claude = safe(claude_sessions, procs, rows)

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
            "claude": claude,
            "runner": safe(agent_runner, claude, self.github),
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
    if pid <= 1:
        return 403, "refusing to stop that process"
    p = safe(read_proc, str(pid))
    if not p or start_ticks(p) != start:
        return 409, "process already exited (or its pid was reused)"
    if p["user"] != ME:
        return 403, "owned by %s; the dashboard runs as %s" % (p["user"], ME)
    if pid == os.getpid():
        # Stopping this dashboard: answer the request first, then exit.
        print("stopping the dashboard itself (pid %d) via dashboard" % pid, flush=True)
        threading.Timer(0.5, os.kill, (pid, signal.SIGTERM)).start()
        return 200, "stopping the dashboard (pid %d)" % pid
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


def set_idle_pause(paused):
    """Creates or removes the flag the idle checker looks for before it counts
    idleness; `devbox-idle pause|resume` on the box does the same."""
    try:
        if paused:
            open(PAUSE_FILE, "a").close()
        elif os.path.exists(PAUSE_FILE):
            os.remove(PAUSE_FILE)
    except OSError as e:
        return 500, ("can't change %s: %s. Re-run ec2/dashboard/install.sh (ssm) so the "
                     "service may write there" % (PAUSE_FILE, e))
    msg = "auto-hibernate %s via dashboard" % ("paused" if paused else "resumed")
    try:  # best effort: the flag is what counts
        with open(IDLE_LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg))
    except OSError:
        pass
    print(msg, flush=True)
    return 200, msg


# ---- http ---------------------------------------------------------------------

STATIC_FILE = re.compile(r"^[a-z][a-z0-9_-]*\.(css|js)\Z")
STATIC_TYPES = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8"}


def read_static(name):
    with open(os.path.join(HERE, "static", name), "rb") as f:
        return f.read()


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
        elif url.path.startswith("/static/"):
            # The page's CSS and JS: a flat directory, names matched whole, so
            # nothing outside it can be asked for.
            m = STATIC_FILE.match(url.path[len("/static/"):])
            body = m and safe(read_static, m.group(0))
            if body is None:
                return self.send(404, b"not found\n", "text/plain")
            self.send(200, body, STATIC_TYPES[m.group(1)])
        elif url.path == "/api/stats":
            self.json(self.sampler.get())
        elif url.path == "/api/log":
            n = int(parse_qs(url.query).get("n", ["100"])[0])
            lines = safe(tail, IDLE_LOG, max(1, min(n, 2000)))
            self.json({"path": IDLE_LOG, "available": lines is not None, "lines": lines or []})
        elif url.path == "/api/runner/run":
            # Run logs can hold secrets the agent read: same checks as a POST,
            # except that browsers leave Origin off same-origin GETs.
            refused = self.refuse_foreign(origin_required=False)
            if refused:
                return self.reply(403, refused)
            d = safe(run_details, parse_qs(url.query).get("log", [""])[0])
            self.json(d) if d else self.send(404, b"no such run log\n", "text/plain")
        elif url.path == "/api/disk-usage":
            # Lists what's in the home directory, and a scan is heavy: same
            # checks as /api/runner/run. Blocks until the scan is done.
            refused = self.refuse_foreign(origin_required=False)
            if refused:
                return self.reply(403, refused)
            self.json(disk_usage(refresh="refresh" in parse_qs(url.query)))
        elif url.path == "/api/session-log":
            # Transcripts hold code, prompts and command output: same checks
            # as /api/runner/run.
            refused = self.refuse_foreign(origin_required=False)
            if refused:
                return self.reply(403, refused)
            q = parse_qs(url.query)
            sid = q.get("id", [""])[0]
            try:
                offset = int(q.get("from", ["-1"])[0])
            except ValueError:
                return self.reply(400, "from must be a byte offset")
            if not SESSION_ID.match(sid):
                return self.reply(400, "expected ?id=<session id>")
            log = safe(session_log, sid, offset)
            if log is None:
                return self.reply(404, "no transcript for that session")
            self.json(log)
        else:
            self.send(404, b"not found\n", "text/plain")

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/stop", "/api/hibernate", "/api/idle-pause", "/api/issue"):
            return self.send(404, b"not found\n", "text/plain")
        refused = self.refuse_foreign()
        if refused:
            return self.reply(403, refused)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            # An issue's body can run long; everything else is a few fields
            body = json.loads(self.rfile.read(min(length, 65536 if path == "/api/issue" else 4096)) or b"{}")
        except ValueError:
            return self.reply(400, "expected a JSON body")
        if path == "/api/issue":
            title, text = body.get("title"), body.get("body", "")
            if not (isinstance(title, str) and title.strip() and isinstance(text, str)):
                return self.reply(400, "expected JSON {repo, title, body}")
            code, message = create_issue(runner_conf(), body.get("repo"), title.strip(), text.strip())
            if code == 200:
                self.sampler.github_now.set()  # so the new issue shows up within seconds
            return self.reply(code, message)
        if path == "/api/hibernate":
            return self.reply(*hibernate(self.sampler.instance, dry_run=body.get("dry_run") is True))
        if path == "/api/idle-pause":
            if not isinstance(body.get("paused"), bool):
                return self.reply(400, "expected JSON {paused: true|false}")
            code, message = set_idle_pause(body["paused"])
            if code == 200:
                safe(self.sampler.sample)  # the page re-polls right after
            return self.reply(code, message)
        try:
            pid, start = int(body["pid"]), int(body["start"])
        except (KeyError, TypeError, ValueError):
            return self.reply(400, "expected JSON {pid, start}")
        code, message = stop_process(pid, start)
        if code == 200:
            self.sampler.resample_soon()
        self.reply(code, message)

    def refuse_foreign(self, origin_required=True):
        """Reason to refuse a request that didn't come from this dashboard's
        own page, or None. A custom header can't be sent cross-origin without
        a CORS preflight, which this server never approves; Origin and Host
        catch the rest, including DNS rebinding."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if self.headers.get("X-Dashboard") != "1":
            return "missing X-Dashboard header"
        if (origin or origin_required) and urlparse(origin or "").netloc != host:
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
