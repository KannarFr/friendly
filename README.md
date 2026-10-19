<div align="center">

<img src="friendly.svg" width="96" alt="friendly logo" />

# friendly

**Dictate or type a rough message, pick a tone, get a polished rewrite on your clipboard.**

A tiny Spotlight-style overlay for Wayland that rewrites your text in a chosen
tone — professional, kind, concise… — using [Claude Code](https://www.anthropic.com/claude-code)
(`claude -p`), then copies the result. Built for a voice-dictation workflow on
Arch + Sway.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![AUR friendly](https://img.shields.io/aur/version/friendly?logo=archlinux&logoColor=white&label=AUR%20friendly&color=1793d1&cacheSeconds=3600)](https://aur.archlinux.org/packages/friendly)
[![AUR friendly-git](https://img.shields.io/aur/version/friendly-git?logo=archlinux&logoColor=white&label=AUR%20friendly-git&color=1793d1&cacheSeconds=3600)](https://aur.archlinux.org/packages/friendly-git)
[![AUR votes](https://img.shields.io/aur/votes/friendly?logo=archlinux&logoColor=white&label=votes&color=1793d1&cacheSeconds=3600)](https://aur.archlinux.org/packages/friendly)
![Wayland](https://img.shields.io/badge/Wayland-wlroots%2Fsway-success)

</div>

<p align="center">
  <img src="docs/demo.gif" width="80%" alt="friendly demo: dictate into the box, pick a tone, get the rewrite on the clipboard" />
</p>

<p align="center">
  <em>One hotkey opens the box (with <code>-l</code>, dictation starts with it); speak, pick a tone, paste the rewrite.</em>
</p>

## Why

You dictate a quick, messy message with your voice — *"yo can we push the call to 3pm, thx"* —
and want a clean version to paste into Slack / email / wherever, in the right tone,
without leaving the keyboard. `friendly` is the glue: a centered text box you dictate
into, a tone picker, and the rewrite lands in your clipboard. The thinking is done by
Claude Code; `friendly` just handles the UI and the clipboard.

## How it works

```
  hotkey ──▶ ┌──────────────────────────┐
             │  centered text area      │   GTK layer-shell overlay (friendly-input.py),
             │  (dictate / type)        │   focus ready — your dictation tool types in it
             └────────────┬─────────────┘
                          │ Enter
             ┌──────────────────────────┐
             │  tone menu (wofi)        │   Professional · Kind · Concise · … · ✏️ Custom
             └────────────┬─────────────┘
                          │
              claude -p ──▶  rewritten text  ──▶  📋 clipboard  +  🔔 notification
```

- **Input** — a multiline text area rendered as a centered `wlr-layer-shell` overlay
  (so it's never tiled by your compositor). `Enter` submits, `Shift+Enter` adds a
  newline, `Esc` cancels. Every shortcut also has a button below the field, labelled
  with its key.
- **Tone** — a `wofi` Spotlight bar lists presets plus a free-form *Custom…* option.
- **Rewrite** — the message + tone are sent to **`claude -p`** (Claude Code's
  non-interactive mode). It uses your existing Claude Code login — no API key to
  manage. The model is told to return *only* the rewritten text.
- **Output** — the result is copied with `wl-copy` and shown in a notification.

> [!NOTE]
> The rewrite runs in the cloud: your text is sent to Anthropic over HTTPS for the
> duration of the request. Keep that in mind for sensitive content. No network → no
> rewrite (the model is remote).

## Install

### From the AUR (recommended)

```bash
# stable
paru -S friendly        # or: yay -S friendly
# or bleeding-edge (builds from git HEAD)
paru -S friendly-git
```

You also need **Claude Code** logged in (`claude`):

```bash
paru -S claude-code      # or: npm i -g @anthropic-ai/claude-code
claude        # run once to authenticate
```

### Debian / Ubuntu

Grab the `.deb` from the [latest release](https://github.com/KannarFr/friendly/releases/latest):

```bash
sudo apt install ./friendly_*_all.deb
# Claude Code is not in Debian/Ubuntu — install it separately:
npm install -g @anthropic-ai/claude-code && claude
```

Build it yourself from a checkout: `cp -r packaging/debian debian && dpkg-buildpackage -b -us -uc`.

### Exherbo

Drop [`packaging/exherbo/friendly.exheres-0`](packaging/exherbo/) into a repository
you own, then `cave resolve -x friendly`. See
[`packaging/exherbo/README.md`](packaging/exherbo/README.md) (verify the dependency
atoms — gtk-layer-shell/wofi may need a personal repo).

### Manual

```bash
git clone https://github.com/KannarFr/friendly
cd friendly
mkdir -p ~/.local/bin ~/.local/share/friendly ~/.local/share/icons/hicolor/scalable/apps ~/.local/share/applications
ln -sf "$PWD/friendly" ~/.local/bin/friendly
cp friendly-input.py spotlight.css friendly.svg ~/.local/share/friendly/
cp friendly.svg ~/.local/share/icons/hicolor/scalable/apps/friendly.svg
ln -sf "$PWD/friendly.desktop" ~/.local/share/applications/friendly.desktop
```

The script finds its resources next to itself **or** in `~/.local/share/friendly`,
`/usr/share/friendly`, etc., so both layouts work.

### macOS / X11

Not supported. The UI is Wayland-only — the centered overlay needs
`wlr-layer-shell` (via `gtk-layer-shell`), the menu uses `wofi`, and the clipboard
uses `wl-copy`. Only `claude -p` is cross-platform. A macOS port would mean
replacing the UI layer (e.g. a native SwiftUI panel or Hammerspoon/Raycast) and
using `pbcopy`; the rewrite logic and prompt would carry over unchanged. Not
planned — open an issue if you want to drive it.

## Bind a key

**Sway** — use an absolute path (Sway's `PATH` may not include `~/.local/bin`):

```
bindsym $mod+y exec /usr/bin/friendly
```

**Hyprland** (`hyprland.conf`):

```
bind = $mainMod, Y, exec, friendly
```

**GNOME** — *Settings → Keyboard → Custom Shortcuts* → command `friendly`.

## Dictation

### Built-in (recommended)

`friendly -d` adds a **● Dictate** button (`Ctrl+R`) to the box. It records the mic and
shows a **● Listening** indicator with a level meter. Press `Enter` (or `Ctrl+R`, or
**Stop**) to stop: the audio is transcribed and the text lands in the field, ready to
edit. Press `Enter` again to submit. `Ctrl+Enter` stops and submits in one go,
`Ctrl+R` again records more (the text is appended), and `Esc` cancels. Each of these
has a button showing its shortcut.

To start recording as soon as the box opens, add `-l` (`--listen`, or set
`FRIENDLY_LISTEN` to `1`/`true`/`yes`/`on`). It turns built-in dictation on by
itself, with the `auto` backend unless `--stt` or `FRIENDLY_STT` picks another:

```
bindsym $mod+y exec /usr/bin/friendly -l
```

The speech-to-text **backend** is pluggable, with `--stt BACKEND` (or `FRIENDLY_STT`):

| Backend | What runs |
| --- | --- |
| `auto` *(what `-d` uses)* | `handy` if installed, else `whisper` |
| `handy` | [Handy](https://github.com/cjpais/Handy)'s headless mode (`handy --transcribe-file`). It uses Handy's installed model and settings and doesn't need the Handy app running, so no Handy window appears |
| `whisper` | [whisper.cpp](https://github.com/ggml-org/whisper.cpp)'s `whisper-cli`, with the model in `FRIENDLY_WHISPER_MODEL` (language: `FRIENDLY_STT_LANG`, default `auto`) |
| any command | e.g. `--stt 'my-stt --lang fr {wav}'`: `{wav}` becomes the path of a 16 kHz mono WAV (it's appended if there is no `{wav}`), and the text is read from stdout |

Recording uses `pw-record` (PipeWire), then falls back to `parecord` and `arecord`.
Transcription starts once you stop, so there is no live text while you speak. With
Handy, a short message takes about 1–2 s, most of it loading the model.

### External dictation tool

Alternatively, pair `friendly` with any tool that types into the focused window, e.g.
[Handy](https://github.com/cjpais/Handy) (the app) or
[nerd-dictation](https://github.com/ideasman42/nerd-dictation).

To **auto-start dictation when the box opens** (so one hotkey does both), pass
`--on-open CMD` — it runs `CMD` once the window is focused. With Handy on Sway:

```
bindsym $mod+y exec /usr/bin/friendly \
  --on-open 'handy --toggle-transcription' --on-cancel 'handy --cancel'
```

Now `$mod+y` opens the box and starts recording; speak, stop your dictation (Handy
types the text into the box), then `Enter`. Pressing `Esc` cancels **and** stops the
dictation via `--on-cancel` (so Handy doesn't keep recording). Both can also be set
globally with the `FRIENDLY_ON_OPEN` / `FRIENDLY_ON_CANCEL` environment variables.

## Usage

GUI:

```bash
friendly
```

CLI / scriptable:

```bash
friendly -s "Professional" "my text"      # preset by name
friendly -i "a very formal tone" "my text"   # free-form instruction
echo "my text" | friendly -s Concise -n     # from a pipe, result on stdout
```

> The rewrite **keeps the language of your message** — dictate in any language and the
> output stays in it; only the tone changes. Presets are editable in `presets.conf`.

| Flag | Meaning |
| --- | --- |
| `-s, --style NAME` | use a preset by name (skip the menu) |
| `-i, --instruction TEXT` | free-form tone instruction (skip the menu) |
| `-o, --on-open CMD` | run `CMD` when the box opens (e.g. start dictation); env: `FRIENDLY_ON_OPEN` |
| `-c, --on-cancel CMD` | run `CMD` on cancel/Esc (e.g. stop dictation); env: `FRIENDLY_ON_CANCEL` |
| `-d, --dictate` | built-in dictation with the `auto` backend (start with `Ctrl+R` or the Dictate button) |
| `-l, --listen` | start recording as soon as the box opens (implies `-d`); env: `FRIENDLY_LISTEN` (`1`/`true`/`yes`/`on`) |
| `--stt BACKEND` | built-in dictation with `BACKEND` (`auto`, `handy`, `whisper`, or a command); env: `FRIENDLY_STT` |
| `-n, --no-copy` | print the result to stdout instead of copying |
| `-h, --help` | help |

`Esc` at any step cancels cleanly (exit 0, nothing copied).

## Configuration

**Tones** live in `~/.config/friendly/presets.conf` (created on first run). One per
line, `Display name|instruction sent to the model`. The **first** preset is the
default — it's highlighted in the menu, so just pressing `Enter` picks it:

```
Pro & kind|a tone that is both professional, kind and composed
Professional|a professional, clear and composed tone
Concise|a more concise and direct phrasing, keeping the essentials
```

**Look** — tweak `spotlight.css` (the `wofi` bars) and the inline CSS in
`friendly-input.py` (the text area): colors, radius, font size, width.

## Dependencies

All in the official Arch repos except Claude Code:

| Package | Role |
| --- | --- |
| `claude-code` *(AUR / npm)* | the LLM backend — `claude -p` (**required**) |
| `python` + `python-gobject` + `gtk-layer-shell` + `gtk3` | the centered text area |
| `wl-clipboard` | clipboard (`wl-copy`) |
| `wofi` | tone menu *(falls back to `rofi`, then `zenity`)* |
| `libnotify` | notifications *(optional but recommended)* |
| `handy` / `handy-bin` *(AUR)* or `whisper.cpp-git` *(AUR)* | speech-to-text for `-d` *(optional)* |
| `pipewire-audio` | mic recording for `-d` (`pw-record`) *(optional)* |

## Packaging / releasing

See [`packaging/README.md`](packaging/README.md). TL;DR: push a `vX.Y.Z` tag and CI
creates the GitHub Release and auto-publishes the `friendly` AUR package.

## License

[MIT](LICENSE) © 2026 KannarFr
