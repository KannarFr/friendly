#!/usr/bin/env python3
"""friendly — zone de texte multiligne centrée (overlay layer-shell), look Spotlight.

Usage : friendly-input.py [invite]
  Entrée        valide (imprime le texte sur stdout, code 0)
  Maj+Entrée    nouvelle ligne
  Échap         annule (rien sur stdout, code 1)
"""
import sys
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GtkLayerShell  # noqa: E402

PROMPT = sys.argv[1] if len(sys.argv) > 1 else "Dicte ton message"

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
            return False  # laisse insérer un saut de ligne
        submit(view)
        return True
    return False


def main():
    win = Gtk.Window()
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
    # pas d'ancrage -> surface centrée
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
        label="Entrée = valider   ·   Maj+Entrée = nouvelle ligne   ·   Échap = annuler",
        xalign=0,
    )
    hint.set_name("hint")
    outer.pack_start(hint, False, False, 0)

    win.add(outer)
    win.connect("key-press-event", on_key, view)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    view.grab_focus()
    Gtk.main()

    if result["text"] is None:
        sys.exit(1)  # annulé
    sys.stdout.write(result["text"])


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise  # 0 = validé, 1 = annulé : codes voulus
    except Exception:
        # échec runtime (layer-shell non supporté, pas d'affichage, CSS…) :
        # code distinct pour que l'appelant retombe sur wofi.
        sys.exit(2)
