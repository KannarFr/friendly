#!/usr/bin/env python3
"""friendly — centered multiline text box (layer-shell overlay), Spotlight look.

Usage: friendly-input.py [--on-open CMD] [prompt]
  Enter         submit (prints the text to stdout, exit 0)
  Shift+Enter   new line
  Esc           cancel (nothing on stdout, exit 1)
  --on-open CMD run CMD (shell) once the window is shown and focused
                — e.g. start dictation that types into the field.
"""
import subprocess
import sys
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, Gdk, GtkLayerShell  # noqa: E402

# Parse argv: --on-open CMD + a positional prompt.
_args = sys.argv[1:]
ON_OPEN = ""
_rest = []
_i = 0
while _i < len(_args):
    if _args[_i] == "--on-open" and _i + 1 < len(_args):
        ON_OPEN = _args[_i + 1]
        _i += 2
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
#hint { color: #6b6f76; font-size: 12px; margin: 10px 8px 2px 8px; }
"""

result = {"text": None}


def submit(view):
    buf = view.get_buffer()
    result["text"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
    Gtk.main_quit()


def on_key(_win, event, view):
    if event.keyval == Gdk.KEY_Escape:
        Gtk.main_quit()
        return True
    if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            return False  # let a newline be inserted
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

    hint = Gtk.Label(
        label="Enter = submit   ·   Shift+Enter = new line   ·   Esc = cancel",
        xalign=0,
    )
    hint.set_name("hint")
    outer.pack_start(hint, False, False, 0)

    win.add(outer)
    win.connect("key-press-event", on_key, view)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    view.grab_focus()

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

    Gtk.main()

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
