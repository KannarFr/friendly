#!/usr/bin/env python3
"""friendly — centered multiline text box (layer-shell overlay), Spotlight look.

Usage: friendly-input.py [--on-open CMD] [--stt BACKEND] [prompt]
  Enter         submit (prints the text to stdout, exit 0)
  Shift+Enter   new line
  Esc           cancel (nothing on stdout, exit 1)
  --on-open CMD run CMD (shell) once the window is shown and focused
                — e.g. start dictation that types into the field.
  --stt BACKEND built-in dictation: record the mic as soon as the box opens,
                transcribe with BACKEND and insert the text in the field.
                BACKEND: auto | handy | whisper | a shell command (the WAV
                path replaces {wav}, or is appended), text read from stdout.
                While recording: Enter = stop & transcribe,
                Ctrl+Enter = stop, transcribe & submit. Ctrl+R = record again.
"""
import array
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, Gdk, GtkLayerShell  # noqa: E402

# Parse argv: --on-open CMD, --stt BACKEND + a positional prompt.
_args = sys.argv[1:]
ON_OPEN = ""
STT = ""
_rest = []
_i = 0
while _i < len(_args):
    if _args[_i] == "--on-open" and _i + 1 < len(_args):
        ON_OPEN = _args[_i + 1]
        _i += 2
    elif _args[_i] == "--stt" and _i + 1 < len(_args):
        STT = _args[_i + 1]
        _i += 2
    else:
        _rest.append(_args[_i])
        _i += 1
PROMPT = _rest[0] if _rest else "Dictate your message"

HINT_TYPING = "Enter = submit   ·   Shift+Enter = new line   ·   Esc = cancel"
HINT_TYPING_STT = HINT_TYPING + "   ·   Ctrl+R = dictate"
HINT_RECORDING = "Enter = stop & transcribe   ·   Ctrl+Enter = stop & submit   ·   Esc = cancel"

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
#hint { color: #6b6f76; font-size: 12px; margin: 10px 8px 2px 8px; }
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


def fix_wav_sizes(wav):
    """Rewrite the RIFF and data sizes from the file size.

    A recorder killed before finalizing leaves them at 0 or stale; the samples
    themselves are fine. Returns the number of audio bytes (0 if unusable).
    """
    try:
        with open(wav, "r+b") as f:
            head = f.read(4096)
            size = f.seek(0, os.SEEK_END)
            if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return 0
            pos = 12
            while pos + 8 <= len(head):
                cid = head[pos:pos + 4]
                clen = int.from_bytes(head[pos + 4:pos + 8], "little")
                if cid == b"data":
                    data = size - (pos + 8)
                    f.seek(4)
                    f.write((size - 8).to_bytes(4, "little"))
                    f.seek(pos + 4)
                    f.write(data.to_bytes(4, "little"))
                    return max(0, data)
                pos += 8 + clen + (clen & 1)
    except OSError:
        pass
    return 0


class Dictation:
    """Records the mic into a temp WAV, then transcribes it off the UI thread."""

    MIN_AUDIO = 3200  # bytes: 100 ms at 16 kHz s16 mono

    def __init__(self, backend, view, status, level, hint):
        self.backend = backend
        self.view, self.status, self.level, self.hint = view, status, level, hint
        self.proc = None  # recorder
        self.wav = None  # file being recorded
        self.files = set()  # every temp WAV not yet deleted
        self.procs = []  # running transcription processes
        self.started = 0.0
        self.busy = False  # transcription in flight
        self.submit_after = False

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
        self.level.set_visible(True)
        self.hint.set_text(HINT_RECORDING)
        self._set_status("●  Listening…  0:00")
        GLib.timeout_add(80, self._tick)

    def _tick(self):
        if not self.recording:
            return False
        if self.proc.poll() is not None:  # recorder died (no mic, …)
            self._finish(died=True)  # still transcribe what it captured
            return False
        secs = int(time.monotonic() - self.started)
        self._set_status("●  Listening…  %d:%02d" % (secs // 60, secs % 60))
        self.level.set_value(self._rms())
        return True

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
        self.hint.set_text(HINT_TYPING_STT)
        self.busy = True
        self._set_status("⏳  Transcribing…", "busy")
        threading.Thread(target=self._transcribe, args=(proc, wav, died),
                         daemon=True).start()

    def _transcribe(self, proc, wav, died):
        text = err = None
        try:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
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
        if err:
            self._set_status(err, "error")
            return False
        self._set_status("" if text else "Nothing heard", "" if text else "error")
        buf = self.view.get_buffer()
        if text:
            # Appending to existing text (Ctrl+R): keep a space between them.
            end = buf.get_end_iter()
            last = end.copy()
            if last.backward_char() and not buf.get_text(last, end, True).isspace():
                text = " " + text
            buf.insert(end, text)
        if submit_after and buf.get_char_count():
            submit(self.view)
        return False

    def abort(self):
        """Cancel: stop recording and transcription, delete every recording."""
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


def on_key(_win, event, view, dictation):
    ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
    if event.keyval == Gdk.KEY_Escape:
        Gtk.main_quit()
        return True
    if dictation and ctrl and event.keyval in (Gdk.KEY_r, Gdk.KEY_R):
        dictation.start()
        return True
    if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            return False  # let a newline be inserted, whatever the dictation state
        if dictation and dictation.recording:
            dictation.stop(submit=bool(ctrl))
            return True
        if dictation and dictation.busy:
            dictation.submit_after = True  # submit as soon as the text lands
            return True
        submit(view)
        return True
    return False


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

    hint = Gtk.Label(label=HINT_TYPING_STT if STT else HINT_TYPING, xalign=0)
    hint.set_name("hint")
    outer.pack_start(hint, False, False, 0)

    dictation = Dictation(STT, view, status, level, hint) if STT else None

    win.add(outer)
    win.connect("key-press-event", on_key, view, dictation)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    view.grab_focus()

    if dictation:
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
