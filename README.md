# Linux app

A tray app for Ubuntu 24.04+, GNOME and KDE Plasma, Wayland first, X11 as a
fallback. Python 3 + PyGObject (GTK 3), one `.deb` for every architecture.
The id is `me.lovearound.LoveAround`; the package and command are
`lovearound`, the Python package `lovearound`, links `lovearound://`.
The old `needed://` links work too: the site still sends them (Google
sign-in, invites) until it moves to `lovearound://` with the other apps.

## Why this stack

The two hard parts are the tray and the full-screen overlay, and neither
toolkit solves them on both shells, so the choice is whatever makes them
least work:

- **Tray:** a StatusNotifierItem + `com.canonical.dbusmenu`, written directly
  on Gio D-Bus (`tray.py`, ~400 lines). KDE shows it natively, Ubuntu's GNOME
  through its AppIndicator extension. No libappindicator (GTK 3 only, no
  left-click), no Qt QSystemTrayIcon quirks, and we get Activate with click
  coordinates.
- **Overlay:** `wlr-layer-shell` via `gtk-layer-shell` (in Ubuntu 24.04 as
  `gir1.2-gtklayershell-0.1`; `gtk4-layer-shell` isn't packaged there, and
  LayerShellQt in 24.04 is Qt 5 only). GNOME has no layer-shell at all, so
  there the glow is drawn by our own GNOME Shell extension, which any stack
  would need.
- GTK 3 still runs on X11 without a fuss, can draw on an RGBA window with an
  empty input shape, and cairo draws the glow the same way in the app and
  (as Cairo in GJS) in the extension.
- Tauri was considered (the Windows port uses it): on Linux its tray is
  libappindicator (no left-click event), transparent click-through windows
  are unreliable on Wayland, and layer-shell would need a GTK side anyway.

## What it does

Same as the [Mac app](https://github.com/lovearound-me/mac#readme):

- A heart in the tray. Its menu is the quick way: "О ком ты сейчас думаешь?…"
  (the window), "Кому-нибудь на свете", the people "рядом" and a few others —
  a click sends a bare signal — then the pause (hour / till morning / until
  removed), Книга…, Настройки…, Проверить обновления…, Закрыть приложение.
  On KDE a left click opens the window and a right click the menu. Ubuntu's
  AppIndicator opens the menu on any click, which is why the menu sends
  signals itself.
- The window: "О ком ты сейчас думаешь?", the sparkles circle for
  "Кому-нибудь на свете", the close people as circles (dragged to reorder),
  "+" to add by link, search over the whole book, "Твой Love ID" with
  "Скопировать"; before that, sign-in.
- The book and the settings (Сигнал / Когда / Устройства / Аккаунт) are
  windows, like on the Mac.
- An incoming signal lights the edges of every screen in the receiver's own
  color, emoji floating up, clicks pass through. The receiver never learns
  who sent it. The sender sees the same effect in the contact's color.
- Light or dark follows the desktop (`org.freedesktop.appearance color-scheme`
  via the portal, then the GTK theme name). Colors and settings stay in
  `~/.config/lovearound/settings.json`; the server stores no colors.
- First launch adds `~/.config/autostart/me.lovearound.LoveAround.desktop`
  (`lovearound --background`) and, on GNOME, turns the extension on.

## The overlay, desktop by desktop

`overlay.Overlay.kind()` picks one at each signal:

| Desktop | How | Covers |
|---|---|---|
| GNOME Shell (Wayland or X11) | our extension `lovearound@lovearound.me`, D-Bus `me.lovearound.Overlay.Play` | everything, top bar and full-screen windows included (unredirect is turned off while it plays) |
| KDE Plasma 5.27/6, Sway, Hyprland… (Wayland) | `wlr-layer-shell`, overlay layer, one surface per output, empty input region | everything |
| X11 with a compositor (KDE X11, Xfce with compositing…) | override-redirect RGBA window per screen, empty input shape | everything but some full-screen games that unredirect |
| X11 without a compositor, other Wayland | a notification "Кто-то сейчас думает о тебе ♥", withdrawn after a minute, + the tray heart flashes | — |

**The GNOME compromise.** Mutter offers no way for an app to draw above
everything, so a GNOME user needs the extension. It comes in the `.deb`
(`/usr/share/gnome-shell/extensions/`), the app adds it to
`org.gnome.shell enabled-extensions` on first launch, but GNOME Shell on
Wayland only notices extensions installed after login at the next login.
Until then (or if the user turns it off in Extensions) a signal arrives as a
notification, and Settings → Сигнал says why, with a "Включить" button when
it can help. Extensions are code inside the Shell: each GNOME release may
need a `shell-version` bump in `metadata.json` (now 45–49; tested on 46) and a test. Not
on extensions.gnome.org; it's a system extension.

## License

MIT (`LICENSE`), all of it: the app, the GNOME Shell extension and the KWin
script. MIT is GPL-compatible, which is what extensions for GNOME Shell and
KWin need. The point of Love Around is that anyone can make their own
receiver of a signal, and this app is meant to be a reference for one.

## Quiet while presenting

`presenting.py`, when "Тихо, когда что-то на весь экран" is on:

- **GNOME:** the extension reports a full-screen window on any monitor and any
  screen cast / remote desktop session (Mutter's remote access controller —
  this one catches screen sharing in Meet, Zoom, OBS through the portal).
  Mirrored displays come from Mutter's `DisplayConfig`.
- **KDE:** a tiny KWin script (`kwin/fullscreen.js`, loaded over
  `org.kde.kwin.Scripting`) reports whether the active window is full screen.
  Screen sharing on KDE isn't visible to apps.
- **X11:** the active window covers a whole monitor.
- Everywhere: two monitors with the same geometry (mirroring).

## Popup placement

- **KDE / wlroots:** a layer-shell surface on the top layer, anchored to the
  corner nearest the click coordinates that come with `Activate`.
- **GNOME Wayland:** apps can't place windows; the extension recognizes the
  popup (app id + title "Love Around") and puts it under the top bar on the
  right, under the heart, keeps it above, and moves it again when it resizes.
  Without the extension it opens where Mutter puts it (centered).
- **X11:** a utility window moved next to the pointer.

The window hides on Escape and on losing focus, like a menu.

## Layout

| Path | Contains |
|---|---|
| `lovearound/config.py` | API base URL, Firebase web API key, site URL, scheme, version; `LOVEAROUND_API` / `_AUTH` / `_TOKEN` point it at a fake server |
| `lovearound/auth.py`, `lovearound/signinbox.py` | Firebase Auth over REST: email+password (sign-up for a new address), reset, refresh, Google via the site (the session sealed to a one-time key); the session in the Secret Service |
| `lovearound/api.py` | `/v1` client; retries once on 401 with a fresh token |
| `lovearound/stream.py` | `WS /v1/stream` (libsoup 3), ping every 30 s, 1→60 s backoff, reconnect after sleep and network changes |
| `lovearound/model.py` | state, local settings, pause, `lovearound://` links |
| `lovearound/tray.py` | StatusNotifierItem + dbusmenu |
| `lovearound/overlay.py`, `lovearound/effect.py` | the effect: GNOME extension / layer-shell / X11 / notification; the glow and emoji in cairo |
| `lovearound/presenting.py`, `kwin/fullscreen.js` | full screen, mirroring, screen sharing |
| `lovearound/system.py` | autostart, links, clipboard, sound (GSound), sleep (logind), GNOME extensions, updates |
| `lovearound/ui/` | the popup, the book, the settings, forms, CSS (`style.py`, the same palette as `Palette.swift`) |
| `gnome-extension/lovearound@lovearound.me/` | the GNOME Shell extension: glow + emoji, presenting, popup placement |
| `data/` | `.desktop` (`x-scheme-handler/lovearound` and the old `…/needed`), AppStream metainfo |
| `tools/make_icons.py` | hicolor PNGs from `icons.app_icon` |
| `install.sh` | where the app's installed files go, for any prefix; `build.sh` packs its `/usr` tree into the `.deb` with the doc and APT files |
| `tests/` | unit tests, `fake_server.py` (Firebase Auth + the server on localhost) |

## Sign-in

- **Email:** `signInWithPassword`, falling back to `signUp` for a new address.
- **Google:** the app opens `https://lovearound.me/signin?state=<uuid>&key=<a
  one-time P-256 public key>` in the browser. The page seals uid, email and
  the refresh token to that key and returns to
  `lovearound://signin?state=…&epk=…&box=…`; the desktop starts
  `lovearound lovearound://…`, `GApplication` hands it to the running
  instance, `signinbox.py` opens the box. The link is useless to anyone else:
  it sits in the process list (any user can read `/proc/<pid>/cmdline`), the
  browser's history, and could go to another app that registered the scheme.
  Until the new page is published the site answers
  `needed://signin?…&uid=…&rt=…` in the clear, which is still accepted. Only
  the state the app generated is accepted.
- The session (uid, email, refresh token) is kept in the Secret Service
  (`libsecret`: GNOME Keyring, or KWallet, which serves the same API on
  Plasma), schema `me.lovearound.LoveAround.Session`. Never in a file. With no
  Secret Service running it stays in memory and the app asks to sign in again
  after a restart.

## Links

- `https://lovearound.me/i/<uid>` → "Открыть приложение" → `lovearound://add/<uid>`
  → the add form in the popup. The `.desktop` file registers the scheme;
  `update-desktop-database` runs on install.

## Build

```sh
sudo apt install python3-cryptography python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-soup-3.0 \
    gir1.2-secret-1 gir1.2-gtklayershell-0.1 gir1.2-gsound-1.0
python3 -m lovearound           # a checkout runs as version "dev"
python3 -m unittest discover -s tests -t .
./build.sh                      # → dist/lovearound_0.2.<N>_all.deb
sudo apt install ./dist/lovearound_0.2.<N>_all.deb
./publish.sh                    # the newest dist/*.deb → a GitHub release
```

`N` is the commit count of this repository (0.1.x came from the old shared
one). `publish.sh` makes it the GitHub release `v0.2.N`, as
`lovearound_0.2.N_all.deb` and `LoveAround.deb`; lovearound.me/download/LoveAround.deb
redirects to the latest one. Normally a release is **Actions → Release → Run workflow** (or
`gh workflow run release -R lovearound-me/linux`): tests, `build.sh` and
`publish.sh` on a GitHub runner. `build.sh` needs only `dpkg-deb`
(and runs `lintian` when it's there). No Flatpak: the sandbox can't install
a GNOME Shell extension, a KWin script or talk layer-shell into the host in
a way that survives, so a Flatpak would always be the notification fallback
on GNOME.

## Other distros

The `.deb` is for Ubuntu and Debian. Elsewhere `install.sh` puts the same files
in place, from a checkout:

```sh
sudo pacman -S python-gobject python-cairo python-cryptography gtk3 libsoup3 \
    libsecret gtk-layer-shell gsound    # Arch; other distros: the same libraries
./install.sh --user                     # into ~/.local, no root
sudo ./install.sh                       # into /usr/local
./install.sh --user --uninstall
```

It stops before touching an earlier install when a Python module or typelib the
app needs is missing (`lovearound/deps.py`), and names them all; it installs no
packages. libsecret, gtk-layer-shell and gsound are optional: without them the
sign-in is kept only until the app quits, KDE and wlroots on Wayland get a
notification instead of the glow, and signals make no sound. `--user`
needs `~/.local/bin` on the session's PATH for the menu entry, the
`lovearound://` links and autostart: fish on CachyOS adds it, plain Arch does
not. A package for another distro runs
`./install.sh --prefix /usr --destdir <staging>`, as `build.sh` does. Nothing
updates such an install: run `install.sh` again after a `git pull`, then quit
the app and start it again.

## Updates

The package adds the APT repository `https://lovearound.me/apt` when installed
from a download, so the desktop's own updater (Software / Discover / unattended
upgrades) and `apt upgrade` update it. A flat repository: `URIs:
https://lovearound.me/`, `Suites: apt/`, `Suite: apt` in `Release`
(with `Suites: ./` apt would ask for `/apt/./InRelease`, which Firebase
redirects to its origin, a 404). It
installs `/etc/apt/sources.list.d/lovearound.sources` (a plain file, not a
conffile, so it goes away with the package) and the key
`/usr/share/keyrings/lovearound.gpg` (`data/lovearound.gpg`).

The repository has no files of its own: each release carries its signed index
(`Packages`, `InRelease`…, written by `tools/make_repo.sh`), and
`firebase.json` in the site repo redirects `/apt/<file>` to the latest release
and `/apt/pool/<version>/<deb>` to the release `v<version>`. So an installed
app sees a version exactly when it is released. The index is signed in CI with
the GitHub secret `APT_SIGNING_KEY` (ed25519, fingerprint
`5B173A2F669393134B8246555B80ECCCD83D2840`, no passphrase); a local
`publish.sh` reads `~/.config/lovearound/apt_signing_key.asc`. Lose that key
and the installed apps never get another update: keep a copy elsewhere.

By hand, for anyone who wants the repository without the download:

```sh
sudo curl -fsSLo /usr/share/keyrings/lovearound.gpg https://lovearound.me/apt/lovearound.gpg
sudo curl -fsSLo /etc/apt/sources.list.d/lovearound.sources https://raw.githubusercontent.com/lovearound-me/linux/main/data/lovearound.sources
sudo apt update && sudo apt install lovearound
```

"Проверить обновления…" opens the desktop's updater. The
running app watches its own `VERSION` file: when apt replaces it, the app
restarts itself into the new version as soon as no window of it is open.

## Not verified yet

Checked headlessly (sway, gnome-shell `--headless`, Xvfb) and with the unit
tests; everything below needs a real machine:

- KDE Plasma at all: layer-shell on KWin, the tray's left click → Activate,
  the KWin script, KWallet as the Secret Service.
- Real clicks in the tray, drag and drop, sound, HiDPI, several monitors,
  sleep/wake.
- Google sign-in through a real browser and `lovearound://` from Firefox/Chrome.
- Screen-sharing detection on GNOME with a real portal session.
- An upgrade by apt over a running app.
