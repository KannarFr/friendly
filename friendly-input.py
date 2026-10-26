#!/usr/bin/env python3
"""friendly — centered multiline text box (layer-shell overlay), Spotlight look.

Usage: friendly-input.py [--on-open CMD] [--stt BACKEND] [--listen] [prompt]
  Enter         submit (prints the text to stdout, exit 0)
  Shift+Enter   new line
  Esc           cancel (nothing on stdout, exit 1)
  Every shortcut also has a button, labelled with its key.
  --on-open CMD run CMD (shell) once the window is shown and focused
                — e.g. start dictation that types into the field.
  --stt BACKEND built-in dictation: Ctrl+R (or the Dictate button) records the
                mic, then BACKEND transcribes it into the field.
                BACKEND: auto | handy | whisper | a shell command (the WAV
                path replaces {wav}, or is appended), text read from stdout.
                While recording: Enter or Ctrl+R = stop & transcribe,
                Ctrl+Enter = stop, transcribe & submit.
  --listen      start recording as soon as the box opens (needs --stt), and
                transcribe live: the recording is cut at pauses and each
                piece lands in the field while you keep talking.
"""
import array
import json
import os
import queue
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, Gdk, GtkLayerShell  # noqa: E402

# Parse argv: --on-open CMD, --stt BACKEND, --listen + a positional prompt.
_args = sys.argv[1:]
ON_OPEN = ""
STT = ""
LISTEN = False
_rest = []
_i = 0
while _i < len(_args):
    if _args[_i] == "--on-open" and _i + 1 < len(_args):
        ON_OPEN = _args[_i + 1]
        _i += 2
    elif _args[_i] == "--stt" and _i + 1 < len(_args):
        STT = _args[_i + 1]
        _i += 2
    elif _args[_i] == "--listen":
        LISTEN = True
        _i += 1
    else:
        _rest.append(_args[_i])
        _i += 1
PROMPT = _rest[0] if _rest else "Dictate your message"


CSS = b"""
window { background-color: rgba(0,0,0,0);
         font-family: "JetBrainsMono Nerd Font","JetBrains Mono",monospace; }
#outer-box {
  padding: 18px;
  border-radius: 22px;
  background-color: rgba(22,22,28,0.96);
  border: 1px solid rgba(255,255,255,0.09);
}
#prompt { color: #aeb4ff; font-size: 14px; margin: 2px 6px 10px 8px; }
#input, #input text {
  font-size: 16px;
  color: #f4f4f6;
  background-color: rgba(255,255,255,0.06);
  caret-color: #9bb0ff;
}
#input { border-radius: 14px; padding: 14px 16px; }
#input text selection { background-color: rgba(120,140,255,0.35); color: #fff; }
#status { color: #ff8f8f; font-size: 13px; margin: 0 8px 8px 8px; }
#status.busy { color: #aeb4ff; }
#status.error { color: #ffb86b; }
#level { margin: 0 8px 10px 8px; min-height: 4px; }
#level trough { background-color: rgba(255,255,255,0.06); border: none; min-height: 4px; }
#level block.filled { background-color: #ff8f8f; border: none; min-height: 4px; }
#level block.empty { background-color: transparent; border: none; }
#bar { margin: 12px 2px 0 2px; }
#bar button {
  background-image: none; background-color: rgba(255,255,255,0.06);
  color: #dcdce0; border: none; border-radius: 10px; box-shadow: none;
  text-shadow: none; padding: 6px 12px; font-size: 13px;
}
#bar button:hover { background-color: rgba(255,255,255,0.12); }
#bar button:disabled { opacity: 0.4; }
#bar button.primary { background-color: rgba(120,140,255,0.30); color: #fff; }
#bar button.primary:hover { background-color: rgba(120,140,255,0.42); }
#bar button.rec { background-color: rgba(255,143,143,0.22); color: #fff; }
#bar button.rec:hover { background-color: rgba(255,143,143,0.34); }
#bar .key { color: #8a8f98; font-size: 12px; margin-left: 8px; }
"""

result = {"text": None}


# --- speech-to-text --------------------------------------------------------
# Every backend takes the path of a 16 kHz mono WAV and returns the text.
# Their processes are registered in `procs` so a cancel can kill them.


def _run(cmd, procs, shell=False):
    # Own process group: killing it also kills what a shell command spawned.
    p = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    procs.append(p)
    try:
        out, err = p.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        _killpg(p)
        raise RuntimeError("timed out")
    finally:
        procs.remove(p)
    if p.returncode != 0:
        msg = (err.strip().splitlines() or ["exit %d" % p.returncode])[-1]
        raise RuntimeError(msg[:200])
    return out


def _killpg(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass


def _whisper_exe():
    return shutil.which("whisper-cli") or shutil.which("whisper-cpp")


def stt_handy(wav, procs):
    # Handy's headless batch path: same models and settings as the app,
    # without its overlay. Logs go to stderr, the JSON result to stdout.
    out = _run(["handy", "--transcribe-file", wav, "--json"], procs)
    for line in reversed(out.splitlines()):
        if line.startswith("{"):
            return json.loads(line).get("text", "")
    raise RuntimeError("handy returned no result")


def stt_whisper(wav, procs):
    exe = _whisper_exe()
    model = os.environ.get("FRIENDLY_WHISPER_MODEL", "")
    if not exe:
        raise RuntimeError("whisper-cli (whisper.cpp) not found")
    if not os.path.isfile(model):
        raise RuntimeError("set FRIENDLY_WHISPER_MODEL to a ggml model file")
    lang = os.environ.get("FRIENDLY_STT_LANG", "auto")
    out = _run([exe, "-m", model, "-l", lang, "-nt", "-np", "-f", wav], procs)
    return " ".join(out.split())  # one line per segment → one paragraph


def stt_command(cmd, wav, procs):
    q = shlex.quote(wav)
    return _run(cmd.replace("{wav}", q) if "{wav}" in cmd else cmd + " " + q,
                procs, shell=True)


def transcribe(backend, wav, procs):
    if backend == "auto":
        if shutil.which("handy"):
            backend = "handy"
        elif _whisper_exe():
            backend = "whisper"
        else:
            raise RuntimeError("no speech-to-text backend found (handy, whisper-cli)")
    if backend == "handy":
        return stt_handy(wav, procs)
    if backend == "whisper":
        return stt_whisper(wav, procs)
    return stt_command(backend, wav, procs)


def recorder_cmd(wav):
    if shutil.which("pw-record"):
        return ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", wav]
    if shutil.which("parecord"):
        return ["parecord", "--rate=16000", "--channels=1", "--format=s16le",
                "--file-format=wav", wav]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "wav", wav]
    return None


def _data_offset(head):
    """Offset of the samples in a WAV whose first bytes are `head` (0 if none)."""
    if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return 0
    pos = 12
    while pos + 8 <= len(head):
        clen = int.from_bytes(head[pos + 4:pos + 8], "little")
        if head[pos:pos + 4] == b"data":
            return pos + 8
        pos += 8 + clen + (clen & 1)
    return 0


def fix_wav_sizes(wav):
    """Rewrite the RIFF and data sizes from the file size.

    A recorder killed before finalizing leaves them at 0 or stale; the samples
    themselves are fine. Returns the number of audio bytes (0 if unusable).
    """
    try:
        with open(wav, "r+b") as f:
            off = _data_offset(f.read(4096))
            size = f.seek(0, os.SEEK_END)
            if not off:
                return 0
            f.seek(4)
            f.write((size - 8).to_bytes(4, "little"))
            f.seek(off - 4)
            f.write((size - off).to_bytes(4, "little"))
            return max(0, size - off)
    except OSError:
        pass
    return 0


def write_chunk(src, start, end):
    """Copy the samples in bytes [start, end) of the WAV being recorded at
    `src` into a new temp WAV (16 kHz s16 mono, like every recorder here)."""
    with open(src, "rb") as f:
        f.seek(start)
        data = f.read(end - start)
    fd, path = tempfile.mkstemp(prefix="friendly-chunk-", suffix=".wav")
    with os.fdopen(fd, "wb") as raw, wave.open(raw, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(data)
    return path


class Dictation:
    """Records the mic into a temp WAV, then transcribes it off the UI thread.

    Live mode cuts the recording at pauses while it runs: each piece is
    transcribed in the background, in order, and lands in the field when
    ready, so only the last piece is left to wait for when recording stops.
    """

    MIN_AUDIO = 3200  # bytes: 100 ms at 16 kHz s16 mono
    BYTES_PER_SEC = 32000
    LIVE_MIN = 4.0  # s: shorter pieces make the backend's language guess unreliable
    LIVE_MAX = 20.0  # s: cut even without a pause
    PAUSE = 0.35  # s of quiet that make a pause
    QUIET = 0.03  # meter level (see _rms) under which the mic counts as quiet

    def __init__(self, backend, view, status, level, on_change, live=False):
        self.backend = backend
        self.view, self.status, self.level = view, status, level
        self.on_change = on_change  # called when recording/busy changes
        self.proc = None  # recorder
        self.wav = None  # file being recorded
        self.files = set()  # every temp WAV not yet deleted
        self.procs = []  # running transcription processes
        self.started = 0.0
        self.busy = False  # transcription in flight
        self.submit_after = False
        self.live = live
        self.aborted = False
        self.data_off = 0  # where the samples start in self.wav (0 = not known yet)
        self.cut = 0  # offset in self.wav up to which pieces were sent
        self.quiet_since = None
        self.pending = 0  # live pieces sent while recording, not landed yet
        self.heard = False  # a live piece produced text
        self.live_err = None
        self.pieces = queue.Queue()  # (piece WAV or None, final, error)
        if live:
            threading.Thread(target=self._live_worker, daemon=True).start()

    @property
    def recording(self):
        return self.proc is not None

    def _set_status(self, text, kind=""):
        ctx = self.status.get_style_context()
        for c in ("busy", "error"):
            ctx.remove_class(c)
        if kind:
            ctx.add_class(kind)
        self.status.set_text(text)
        self.status.set_visible(bool(text))

    def _unlink(self, path):
        self.files.discard(path)
        try:
            os.unlink(path)
        except OSError:
            pass

    def start(self):
        if self.recording or self.busy:
            return
        if not recorder_cmd(""):
            self._set_status("No recorder found (pw-record, parecord, arecord)", "error")
            return
        fd, wav = tempfile.mkstemp(prefix="friendly-", suffix=".wav")
        os.close(fd)
        self.files.add(wav)
        try:
            self.proc = subprocess.Popen(recorder_cmd(wav), stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
        except OSError as e:
            self._unlink(wav)
            self._set_status("Recorder failed: %s" % e, "error")
            return
        self.wav = wav
        self.started = time.monotonic()
        self.data_off = self.cut = 0
        self.quiet_since = self.live_err = None
        self.heard = False
        self.level.set_visible(True)
        self.on_change()
        self._set_status("●  Listening…  0:00")
        GLib.timeout_add(80, self._tick)

    def _tick(self):
        if not self.recording:
            return False
        if self.proc.poll() is not None:  # recorder died (no mic, …)
            self._finish(died=True)  # still transcribe what it captured
            return False
        secs = int(time.monotonic() - self.started)
        lvl = self._rms()
        self.level.set_value(lvl)
        if self.live:
            self._maybe_cut(lvl)
        self._set_status("●  Listening…  %d:%02d%s" % (
            secs // 60, secs % 60, "   ⏳ transcribing" if self.pending else ""))
        return True

    def _maybe_cut(self, lvl):
        # Send what was said since the last cut once it is long enough and
        # the speaker pauses, so a piece rarely ends in the middle of a word.
        now = time.monotonic()
        if lvl >= self.QUIET:
            self.quiet_since = None
        elif self.quiet_since is None:
            self.quiet_since = now
        try:
            if not self.data_off:
                with open(self.wav, "rb") as f:
                    self.data_off = self.cut = _data_offset(f.read(4096))
                if not self.data_off:
                    return  # header not written yet
            end = os.path.getsize(self.wav)
        except OSError:
            return
        end -= (end - self.data_off) % 2  # whole samples only
        secs = (end - self.cut) / self.BYTES_PER_SEC
        paused = self.quiet_since is not None and now - self.quiet_since >= self.PAUSE
        if secs >= self.LIVE_MAX or (secs >= self.LIVE_MIN and paused):
            self.pending += 1
            self._send(self.wav, self.cut, end, final=False)
            self.cut = end

    def _send(self, wav, start, end, final, err=None):
        """Queue the samples in [start, end) of `wav` for the live worker."""
        piece = None
        if end - start >= self.MIN_AUDIO:
            try:
                piece = write_chunk(wav, start, end)
                self.files.add(piece)
            except OSError as e:
                err = err or "Transcription failed: %s" % e
        self.pieces.put((piece, final, err))

    def _live_worker(self):
        # One piece at a time, in order, so the text lands in the order spoken.
        while True:
            piece, final, err = self.pieces.get()
            text = None
            if piece and not self.aborted:
                try:
                    text = transcribe(self.backend, piece, self.procs).strip()
                except Exception as e:  # noqa: BLE001 — shown to the user
                    err = "Transcription failed: %s" % (str(e) or e.__class__.__name__)
            if piece:
                self._unlink(piece)
            if not self.aborted:
                GLib.idle_add(self._live_landed, text or "", final, err)

    def _live_landed(self, text, final, err):
        if err:
            self.live_err = err
        if final:
            self._done(text, self.live_err)
            return False
        self.pending -= 1
        if text:
            self.heard = True
            self._append(text)
        return False

    def _rms(self):
        # Loudness of the last ~100 ms written to the WAV (cosmetic meter).
        try:
            with open(self.wav, "rb") as f:
                size = f.seek(0, os.SEEK_END)
                if size <= 3244:
                    return 0.0
                f.seek(size - 3200 - (size % 2))
                samples = array.array("h", f.read(3200))
        except OSError:
            return 0.0
        if not samples:
            return 0.0
        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
        return min(1.0, rms / 6000.0)

    def stop(self, submit=False):
        """Stop recording and transcribe; submit afterwards if asked."""
        if not self.recording:
            return
        self.submit_after = submit
        self.proc.send_signal(signal.SIGINT)  # lets the recorder finalize the WAV
        self._finish()

    def _finish(self, died=False):
        # The recorder is reaped in the worker thread, so a slow exit never
        # freezes the UI.
        proc, wav = self.proc, self.wav
        self.proc = self.wav = None
        self.level.set_visible(False)
        self.busy = True
        self.on_change()
        self._show_transcribing()
        if self.live:
            target, args = self._finish_live, (proc, wav, died, self.data_off, self.cut)
        else:
            target, args = self._transcribe, (proc, wav, died)
        threading.Thread(target=target, args=args, daemon=True).start()

    def _show_transcribing(self):
        then = ", then submitting" if self.submit_after else ""
        self._set_status("⏳  Transcribing%s…" % then, "busy")

    def queue_submit(self):
        """Submit as soon as the transcription in flight lands."""
        self.submit_after = True
        self._show_transcribing()
        self.on_change()

    @staticmethod
    def _reap(proc):
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _finish_live(self, proc, wav, died, data_off, cut):
        # Queue what follows the last cut as the final piece, behind the
        # pieces still in flight.
        err = None
        try:
            self._reap(proc)
            audio = fix_wav_sizes(wav)
            if not data_off:
                with open(wav, "rb") as f:
                    data_off = cut = _data_offset(f.read(4096))
            if audio < self.MIN_AUDIO:
                err = "Recording stopped unexpectedly" if died else "No audio recorded"
            self._send(wav, cut, data_off + audio, final=True, err=err)
        except OSError as e:
            self.pieces.put((None, True, "Transcription failed: %s" % e))
        finally:
            self._unlink(wav)

    def _transcribe(self, proc, wav, died):
        text = err = None
        try:
            self._reap(proc)
            # Normally a no-op; repairs the header if the recorder was killed.
            if fix_wav_sizes(wav) < self.MIN_AUDIO:
                err = "Recording stopped unexpectedly" if died else "No audio recorded"
            else:
                text = transcribe(self.backend, wav, self.procs).strip()
        except Exception as e:  # noqa: BLE001 — shown to the user, box stays usable
            err = "Transcription failed: %s" % (str(e) or e.__class__.__name__)
        finally:
            self._unlink(wav)
        GLib.idle_add(self._done, text or "", err)

    def _done(self, text, err):
        self.busy = False
        submit_after, self.submit_after = self.submit_after, False
        self.on_change()
        if err:
            self._set_status(err, "error")
            return False
        heard = bool(text) or self.heard
        self._set_status("" if heard else "Nothing heard", "" if heard else "error")
        self._append(text)
        if submit_after and self.view.get_buffer().get_char_count():
            submit(self.view)
        return False

    def _append(self, text):
        if not text:
            return
        # Appending to existing text (Ctrl+R, live pieces): keep a space between them.
        buf = self.view.get_buffer()
        end = buf.get_end_iter()
        last = end.copy()
        if last.backward_char() and not buf.get_text(last, end, True).isspace():
            text = " " + text
        buf.insert(end, text)

    def abort(self):
        """Cancel: stop recording and transcription, delete every recording."""
        self.aborted = True
        if self.proc:
            self.proc.kill()
            self.proc.wait()
            self.proc = None
        for p in list(self.procs):
            _killpg(p)
        for wav in list(self.files):
            self._unlink(wav)


# --- UI ----------------------------------------------------------------------


def submit(view):
    buf = view.get_buffer()
    result["text"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
    Gtk.main_quit()


class Actions:
    """What each shortcut does; the buttons call the same methods."""

    def __init__(self, view):
        self.view = view
        self.dictation = None

    def enter(self, ctrl=False):
        d = self.dictation
        if d and d.recording:
            d.stop(submit=ctrl)
        elif d and d.busy:
            d.queue_submit()
        else:
            submit(self.view)

    def newline(self):
        # Like typing it: replace the selection, then keep the cursor in view.
        buf, editable = self.view.get_buffer(), self.view.get_editable()
        buf.begin_user_action()
        buf.delete_selection(True, editable)
        buf.insert_interactive_at_cursor("\n", -1, editable)
        buf.end_user_action()
        self.view.scroll_mark_onscreen(buf.get_insert())

    def dictate(self):
        # Ctrl+R toggles: start recording, or stop and transcribe.
        d = self.dictation
        if d and d.recording:
            d.stop()
        elif d:
            d.start()

    def cancel(self):
        Gtk.main_quit()


def on_key(_win, event, actions):
    ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
    if event.keyval == Gdk.KEY_Escape:
        actions.cancel()
        return True
    if actions.dictation and ctrl and event.keyval in (Gdk.KEY_r, Gdk.KEY_R):
        actions.dictate()
        return True
    if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            return False  # let a newline be inserted, whatever the dictation state
        actions.enter(ctrl=bool(ctrl))
        return True
    return False


class Bar:
    """Row of buttons, one per shortcut, each showing its key."""

    def __init__(self, actions, view):
        self.actions, self.view = actions, view
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.box.set_name("bar")
        self.dictate = self._button("Dictate", "Ctrl+R", actions.dictate)
        self.box.pack_start(self.dictate, False, False, 0)
        self.newline = self._button("New line", "Shift+Enter", actions.newline)
        self.box.pack_start(self.newline, False, False, 0)
        self.submit = self._button("Submit", "Enter", lambda: actions.enter())
        self.submit.get_style_context().add_class("primary")
        self.box.pack_end(self.submit, False, False, 0)
        self.stop_submit = self._button("Stop & submit", "Ctrl+Enter",
                                        lambda: actions.enter(ctrl=True))
        self.box.pack_end(self.stop_submit, False, False, 0)
        self.cancel = self._button("Cancel", "Esc", actions.cancel)
        self.box.pack_end(self.cancel, False, False, 0)
        # Shown only with dictation / while recording.
        self.dictate.set_no_show_all(True)
        self.dictate.get_child().show_all()
        self.stop_submit.set_no_show_all(True)
        self.stop_submit.get_child().show_all()

    def _button(self, text, key, action):
        b = Gtk.Button()
        b.set_can_focus(False)  # the text field keeps the keyboard
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        b.text = Gtk.Label(label=text)
        inner.pack_start(b.text, False, False, 0)
        k = Gtk.Label(label=key)
        k.get_style_context().add_class("key")
        inner.pack_start(k, False, False, 0)
        b.add(inner)
        b.connect("clicked", lambda _b: (action(), self.view.grab_focus()))
        return b

    def update(self):
        d = self.actions.dictation
        recording = bool(d and d.recording)
        busy = bool(d and d.busy)
        self.dictate.set_visible(d is not None)
        self.dictate.set_sensitive(not busy)
        self.dictate.text.set_text("■  Stop" if recording else "●  Dictate")
        ctx = self.dictate.get_style_context()
        (ctx.add_class if recording else ctx.remove_class)("rec")
        self.stop_submit.set_visible(recording)
        queued = busy and d.submit_after
        self.submit.set_sensitive(not queued)
        self.submit.text.set_text("Stop & transcribe" if recording
                                  else "Submitting after transcription…" if queued
                                  else "Submit")


def main():
    win = Gtk.Window()
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
    # no anchoring -> centered surface
    win.set_size_request(900, 460)

    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    outer.set_name("outer-box")

    label = Gtk.Label(label=PROMPT, xalign=0)
    label.set_name("prompt")
    outer.pack_start(label, False, False, 0)

    # Dictation status + mic level (only shown with --stt).
    status = Gtk.Label(xalign=0)
    status.set_name("status")
    status.set_no_show_all(True)
    outer.pack_start(status, False, False, 0)
    level = Gtk.LevelBar()
    level.set_name("level")
    level.set_no_show_all(True)
    outer.pack_start(level, False, False, 0)

    view = Gtk.TextView()
    view.set_name("input")
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.set_left_margin(4)
    view.set_right_margin(4)
    view.set_top_margin(4)
    view.set_bottom_margin(4)

    scroll = Gtk.ScrolledWindow()
    scroll.set_name("input")
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_vexpand(True)
    scroll.add(view)
    outer.pack_start(scroll, True, True, 0)

    actions = Actions(view)
    bar = Bar(actions, view)
    outer.pack_start(bar.box, False, False, 0)

    dictation = Dictation(STT, view, status, level, bar.update, live=LISTEN) if STT else None
    actions.dictation = dictation
    bar.update()

    win.add(outer)
    win.connect("key-press-event", on_key, actions)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    view.grab_focus()

    if dictation and LISTEN:
        dictation.start()

    # Once the window is mapped/focused, run the on-open command (e.g.
    # dictation). A short delay lets the compositor give keyboard focus to the
    # overlay, so synthetic typing lands in the field.
    if ON_OPEN:
        def _fire_on_open():
            try:
                subprocess.Popen(ON_OPEN, shell=True, start_new_session=True)
            except Exception:
                pass
            return False  # one-shot
        GLib.timeout_add(250, _fire_on_open)

    try:
        Gtk.main()
    finally:
        if dictation:
            dictation.abort()

    if result["text"] is None:
        sys.exit(1)  # cancelled
    sys.stdout.write(result["text"])


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise  # 0 = submitted, 1 = cancelled: intended codes
    except Exception:
        # runtime failure (layer-shell unsupported, no display, CSS…):
        # distinct code so the caller falls back to wofi.
        sys.exit(2)
