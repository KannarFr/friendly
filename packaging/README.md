# Packaging

friendly is a bash + Python script — nothing is compiled (`arch: all`/`any`).
Every package installs the same files: the `friendly` script in `/usr/bin`, its
resources in `/usr/share/friendly` (`friendly-input.py`, `spotlight.css`,
`friendly.svg`), a scalable icon, the `.desktop` entry, and the MIT license.
`claude` (Claude Code) is the runtime backend and is **not** packaged on any
distro — install it via the AUR or `npm i -g @anthropic-ai/claude-code`.

| Target | Directory | How |
| --- | --- | --- |
| Arch `friendly` | [`aur/`](aur/) | source tarball of a `v*` GitHub release (auto-published on tag) |
| Arch `friendly-git` | [`aur-git/`](aur-git/) | git `HEAD` (`provides`/`conflicts` `friendly`) |
| Debian / Ubuntu | [`debian/`](debian/) | `.deb` built in CI and attached to the release |
| Exherbo | [`exherbo/`](exherbo/) | `exheres-0` you drop into your own repo |

The deps map per distro:

| Need | Arch | Debian/Ubuntu | Exherbo |
| --- | --- | --- | --- |
| Python + GI | `python` `python-gobject` | `python3` `python3-gi` | `dev-lang/python` `dev-python/pygobject` |
| GTK 3 | `gtk3` | `gir1.2-gtk-3.0` | `x11-libs/gtk+:3` |
| layer-shell | `gtk-layer-shell` | `gir1.2-gtklayershell-0.1` | `gui/gtk-layer-shell` |
| clipboard | `wl-clipboard` | `wl-clipboard` | `sys-apps/wl-clipboard` |
| menu | `wofi` | `wofi` | `gui/wofi` |
| notify | `libnotify` | `libnotify-bin` | `x11-libs/libnotify` |

## How releasing works

Cutting a release is a single tag:

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
```

The `release` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
then, on any `v*` tag:

1. creates a **GitHub Release** with auto-generated notes (the source tarball is
   produced automatically by GitHub at `…/archive/refs/tags/vX.Y.Z.tar.gz`);
2. pins `pkgver` in `aur/PKGBUILD` to the tag, runs **`updpkgsums`** against that
   tarball, regenerates `.SRCINFO`, and **pushes `friendly` to the AUR** via
   [`KSXGitHub/github-actions-deploy-aur`](https://github.com/KSXGitHub/github-actions-deploy-aur);
3. mirrors the released `pkgver`/`sha256sums` back into `aur/{PKGBUILD,.SRCINFO}`
   on `main` with a `[skip ci]` commit, so the in-repo copy always matches;
4. builds the **`.deb`** (`deb` job) from `packaging/debian/` and attaches
   `friendly_<ver>_all.deb` to the same GitHub Release.

You never bump `pkgver`/`sha256sums` by hand. **Exherbo** is not auto-published —
bump the exheres filename version in your own repository when you want it.

### AUR credentials

The AUR push authenticates with a repo secret **`AUR_SSH_PRIVATE_KEY`** (an AUR
SSH private key — the only credential involved; the automatic `GITHUB_TOKEN`
used for the GitHub Release has no AUR access). It must be **passphrase-less**
(CI can't type one) and its public half must be on the AUR account. To set or
rotate it:

```bash
gh secret set AUR_SSH_PRIVATE_KEY --repo KannarFr/friendly < ~/.ssh/aur
```

### First-time AUR setup (creates the packages)

The AUR is a separate git host from GitHub; the first push to a package's repo
creates it. With an AUR account + SSH key configured locally:

```bash
# stable package
git clone ssh://aur@aur.archlinux.org/friendly.git
cp packaging/aur/{PKGBUILD,.SRCINFO} friendly/
cd friendly && git add PKGBUILD .SRCINFO && git commit -m "Initial import" && git push
cd ..

# VCS package (its pkgver auto-derives per build; only re-push when PKGBUILD changes)
git clone ssh://aur@aur.archlinux.org/friendly-git.git
cp packaging/aur-git/{PKGBUILD,.SRCINFO} friendly-git/
cd friendly-git && git add PKGBUILD .SRCINFO && git commit -m "Initial import" && git push
```

After that, the stable `friendly` package updates itself on every `vX.Y.Z` tag.

## Validate locally

```bash
cd packaging/aur     # or aur-git
makepkg --printsrcinfo > .SRCINFO   # regenerate after editing PKGBUILD
namcap PKGBUILD                     # lint (pacman-contrib / namcap)
makepkg -si                         # build + install
```
