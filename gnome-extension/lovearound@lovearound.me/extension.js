// SPDX-License-Identifier: MIT
// Copyright Love Around
// Love Around for GNOME Shell. Mutter has no layer-shell, and an app window
// can neither cover the top bar nor stay above a full-screen window, so the
// app asks the Shell to draw its signal: me.lovearound.Overlay on the session
// bus, at /me/lovearound/Overlay under org.gnome.Shell. The effect is the
// same as the app's own (lovearound/effect.py) and the Mac's.

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import Graphene from 'gi://Graphene';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// The app's popup, a plain window to Mutter: put under the top bar, on the
// right, where the tray icon is, and above other windows like a menu.
const APP_ID = 'me.lovearound.LoveAround';
const POPUP_TITLE = 'Love Around';

const IFACE = `
<node>
  <interface name="me.lovearound.Overlay">
    <method name="Play">
      <arg type="s" direction="in" name="color"/>
      <arg type="as" direction="in" name="emoji"/>
      <arg type="i" direction="in" name="count"/>
      <arg type="b" direction="in" name="calm"/>
    </method>
    <method name="Presenting">
      <arg type="b" direction="out" name="presenting"/>
    </method>
    <property name="Version" type="u" access="read"/>
  </interface>
</node>`;

const GLOW_DURATION = 2.6;
const MAX_EMOJI = 60;
// Three flashes in 2.6 s, about 1 Hz: well below the 3 Hz flash limit.
const FLASH = [[0, 1, 0.25, 1, 0.25, 1, 0], [0, 0.12, 0.28, 0.45, 0.61, 0.78, 1]];
const CALM = [[0, 0.7, 0.7, 0], [0, 0.3, 0.7, 1]];
const FADE = [[0, 1, 1, 0], [0, 0.1, 0.8, 1]];

function cubicBezier(x1, y1, x2, y2, x) {
    if (x <= 0)
        return 0;
    if (x >= 1)
        return 1;
    let lo = 0, hi = 1, t = x;
    for (let i = 0; i < 30; i++) {
        const cx = 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3;
        if (Math.abs(cx - x) < 1e-5)
            break;
        if (cx < x)
            lo = t;
        else
            hi = t;
        t = (lo + hi) / 2;
    }
    return 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3;
}

const easeInOut = x => cubicBezier(0.42, 0, 0.58, 1, x);

function keyframes([values, times], x, ease = null) {
    if (x <= times[0])
        return values[0];
    for (let i = 1; i < times.length; i++) {
        if (x <= times[i]) {
            let f = (x - times[i - 1]) / (times[i] - times[i - 1]);
            if (ease)
                f = ease(f);
            return values[i - 1] + (values[i] - values[i - 1]) * f;
        }
    }
    return values[values.length - 1];
}

const uniform = (a, b) => a + Math.random() * (b - a);

function parseColor(hex) {
    const m = /^#([0-9a-f]{6})$/i.exec(hex);
    const n = m ? parseInt(m[1], 16) : 0xE86A9A;
    return [(n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF];
}

function drawGlow(area, [r, g, b]) {
    const cr = area.get_context();
    const [width, height] = area.get_surface_size();
    const band = 60 * St.ThemeContext.get_for_stage(global.stage).scale_factor;
    const stops = [[0, 0.9], [0.2, 0.72], [0.55, 0.28], [1, 0]];
    for (const [x0, y0, x1, y1, rect] of [
        [0, 0, 0, band, [0, 0, width, band]],
        [0, height, 0, height - band, [0, height - band, width, band]],
        [0, 0, band, 0, [0, 0, band, height]],
        [width, 0, width - band, 0, [width - band, 0, band, height]],
    ]) {
        const gradient = new Cairo.LinearGradient(x0, y0, x1, y1);
        for (const [offset, a] of stops)
            gradient.addColorStopRGBA(offset, r / 255, g / 255, b / 255, a);
        cr.setSource(gradient);
        cr.rectangle(...rect);
        cr.fill();
    }
    cr.$dispose();
}

/** One signal on one monitor: a glow actor and the emoji labels. */
class Effect {
    constructor(monitor, rgb, emoji, count, calm, scale) {
        this.calm = calm;
        this.actor = new St.Widget({
            reactive: false,
            x: monitor.x, y: monitor.y, width: monitor.width, height: monitor.height,
            clip_to_allocation: true,
        });
        // A soft haze fading inward from the edges, with no crisp frame line:
        // drawn as in effect.py (St's inset box-shadow does not paint here).
        this.glow = new St.DrawingArea({
            reactive: false,
            width: monitor.width, height: monitor.height,
            opacity: 0,
        });
        this.glow.connect('repaint', area => drawGlow(area, rgb));
        this.actor.add_child(this.glow);
        this.particles = [];
        const n = calm || emoji.length === 0 ? 0 : Math.max(0, Math.min(MAX_EMOJI, count));
        const w = monitor.width, h = monitor.height;
        for (let i = 0; i < n; i++) {
            const size = uniform(24, 46);
            const label = new St.Label({
                text: emoji[Math.floor(Math.random() * emoji.length)],
                style: `font-size: ${size.toFixed(1)}px; font-family: "Noto Color Emoji", sans-serif;`,
                opacity: 0,
                pivot_point: new Graphene.Point({x: 0.5, y: 0.5}),
            });
            this.actor.add_child(label);
            const p = {
                label, size: size * scale,
                duration: uniform(3, 4.6), delay: uniform(0, 1.3),
                x: uniform(w * 0.04, w * 0.92), rise: h * uniform(0.45, 0.9),
                drift: uniform(-60, 60) * scale,
                sway: uniform(14, 30) * scale * (Math.random() < 0.5 ? 1 : -1),
                tilt: uniform(0.1, 0.28), h,
            };
            this.particles.push(p);
        }
        this.duration = Math.max(GLOW_DURATION, ...this.particles.map(p => p.delay + p.duration));
    }

    frame(t) {
        this.glow.opacity = t < GLOW_DURATION
            ? Math.round(255 * keyframes(this.calm ? CALM : FLASH, t / GLOW_DURATION, easeInOut)) : 0;
        for (const p of this.particles) {
            const local = (t - p.delay) / p.duration;
            if (local < 0 || local > 1) {
                p.label.opacity = 0;
                continue;
            }
            const k = cubicBezier(0.22, 0.7, 0.3, 1, local);
            // Start below the bottom edge, rise on a smooth S.
            const u = 1 - k;
            const pts = [
                [p.x, p.h + p.size],
                [p.x + p.sway, p.h - p.rise * 0.35],
                [p.x + p.drift - p.sway, p.h - p.rise * 0.7],
                [p.x + p.drift, p.h - p.rise],
            ];
            const at = i => u ** 3 * pts[0][i] + 3 * u * u * k * pts[1][i] + 3 * u * k * k * pts[2][i] + k ** 3 * pts[3][i];
            const [lw, lh] = [p.label.width, p.label.height];
            p.label.set_position(at(0) - lw / 2, at(1) - lh / 2);
            p.label.opacity = Math.round(255 * keyframes(FADE, k));
            const grow = 0.6 + 0.4 * k;
            p.label.set_scale(grow, grow);
            p.label.rotation_angle_z = keyframes([[0, p.tilt, -p.tilt, 0], [0, 0.35, 0.65, 1]], k) * 180 / Math.PI;
        }
    }
}

export default class LoveAroundExtension extends Extension {
    enable() {
        this._effects = [];
        this._timeline = null;
        this._unredirectOff = false;
        // Screen sharing and recording sessions now running.
        this._handles = new Set();
        this._handleIds = [];
        const controller = global.backend.get_remote_access_controller?.();
        if (controller) {
            this._controller = controller;
            this._controllerId = controller.connect('new-handle', (c, handle) => {
                this._handles.add(handle);
                this._handleIds.push([handle, handle.connect('stopped', () => this._handles.delete(handle))]);
            });
        }
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/me/lovearound/Overlay');
        this._windowCreatedId = global.display.connect('window-created', (display, win) => this._placePopup(win));
    }

    _placePopup(win) {
        const actor = win.get_compositor_private();
        if (!actor)
            return;
        // On Wayland the app id and title arrive after 'window-created'.
        const id = actor.connect('first-frame', () => {
            actor.disconnect(id);
            if (win.get_gtk_application_id?.() !== APP_ID || win.get_title() !== POPUP_TITLE)
                return;
            // Its right edge stays put as the content changes its height and width.
            const place = () => {
                const area = win.get_work_area_for_monitor(win.get_monitor());
                const frame = win.get_frame_rect();
                win.move_frame(true, area.x + area.width - frame.width - 8, area.y + 6);
            };
            win.move_to_monitor(global.display.get_current_monitor());
            place();
            win.make_above();
            const sized = win.connect('size-changed', place);
            const gone = win.connect('unmanaged', () => {
                win.disconnect(sized);
                win.disconnect(gone);
            });
        });
    }

    disable() {
        global.display.disconnect(this._windowCreatedId);
        this._stop();
        this._dbus?.unexport();
        this._dbus = null;
        if (this._controller)
            this._controller.disconnect(this._controllerId);
        for (const [handle, id] of this._handleIds)
            handle.disconnect(id);
        this._controller = null;
        this._handleIds = [];
        this._handles = null;
    }

    get Version() {
        return 1;
    }

    Presenting() {
        const display = global.display;
        for (let i = 0; i < display.get_n_monitors(); i++) {
            if (display.get_monitor_in_fullscreen(i))
                return true;
        }
        return this._handles.size > 0;
    }

    Play(color, emoji, count, calm) {
        // The lock screen is not the place, and its shield is above us anyway.
        if (Main.sessionMode.isLocked || Main.screenShield?.locked)
            return;
        this._stop();
        const rgb = parseColor(color);
        const scale = St.ThemeContext.get_for_stage(global.stage).scale_factor;
        for (const monitor of Main.layoutManager.monitors) {
            const fx = new Effect(monitor, rgb, emoji.slice(0, 64), count, calm, scale);
            Main.uiGroup.add_child(fx.actor);
            Main.uiGroup.set_child_above_sibling(fx.actor, null);
            this._effects.push(fx);
        }
        // A full-screen window bypasses compositing unless told not to:
        // the glow would not show over a video.
        this._setUnredirect(false);
        const longest = Math.max(...this._effects.map(fx => fx.duration));
        this._timeline = new Clutter.Timeline({actor: Main.uiGroup, duration: Math.round(longest * 1000) + 300});
        this._timeline.connect('new-frame', (tl, msecs) => {
            for (const fx of this._effects)
                fx.frame(msecs / 1000);
        });
        this._timeline.connect('completed', () => this._stop());
        this._timeline.start();
    }

    _stop() {
        if (this._timeline) {
            const timeline = this._timeline;
            this._timeline = null;
            timeline.stop();
        }
        for (const fx of this._effects ?? [])
            fx.actor.destroy();
        this._effects = [];
        this._setUnredirect(true);
    }

    _setUnredirect(on) {
        if (on === !this._unredirectOff)
            return;
        this._unredirectOff = !on;
        const compositor = global.compositor;
        if (compositor?.disable_unredirect)
            on ? compositor.enable_unredirect() : compositor.disable_unredirect();
        else
            on ? global.enable_unredirect?.() : global.disable_unredirect?.();
    }
}
