# Exherbo packaging

[`friendly.exheres-0`](friendly.exheres-0) is an exheres for Paludis. Exherbo has
no central package upload (like the AUR); you drop the exheres into a repository
you own and sync it.

## Install into a personal repository

```bash
# inside your repository (e.g. ::local), category is up to you:
mkdir -p packages/app-misc/friendly
cp friendly.exheres-0 packages/app-misc/friendly/friendly-0.1.0.exheres-0
# regenerate metadata, then:
cave resolve -x friendly
```

The file uses `require github [ user=KannarFr tag=v${PV} ]`, so it fetches the
GitHub source tarball for tag `v<version>`. For a new release, copy the exheres to
`friendly-<newversion>.exheres-0` (the version comes from the filename).

## Dependency atoms — verify before use

Exherbo category/package names differ between repositories. Double-check these and
adjust to what your synced repos provide:

| Need | Atom used here | Notes |
| --- | --- | --- |
| Python 3 | `dev-lang/python` | |
| PyGObject | `dev-python/pygobject:3` | the `gi` bindings |
| GTK 3 | `x11-libs/gtk+:3` | |
| gtk-layer-shell | `gui/gtk-layer-shell` | **may be absent from ::arbor** — add to a personal repo if needed |
| wl-clipboard | `sys-apps/wl-clipboard` | provides `wl-copy` |
| wofi (suggestion) | `gui/wofi` | tone menu; falls back to rofi/zenity |
| libnotify (suggestion) | `x11-libs/libnotify` | notifications |

`claude-code` (the `claude` CLI) is **required at runtime** and is not in Exherbo —
install it out of band: `npm install -g @anthropic-ai/claude-code`.
