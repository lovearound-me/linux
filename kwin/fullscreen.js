// SPDX-License-Identifier: MIT
// Copyright Love Around
// Loaded into KWin by Love Around (lovearound/presenting.py): tells the app
// whether the active window is full screen. On Wayland an app has no other
// way to know. KWin 6 names are tried first, KWin 5 ones after.
var activated = workspace.windowActivated || workspace.clientActivated;
var current = null;

function report() {
    var full = !!(current && current.fullScreen);
    callDBus("me.lovearound.LoveAround", "/me/lovearound/LoveAround/KWin",
             "me.lovearound.KWin", "SetFullScreen", full);
}

function watch(window) {
    if (current && current.fullScreenChanged) {
        try {
            current.fullScreenChanged.disconnect(report);
        } catch (e) {
            // already gone
        }
    }
    current = window;
    if (current && current.fullScreenChanged) {
        current.fullScreenChanged.connect(report);
    }
    report();
}

activated.connect(watch);
watch(workspace.activeWindow || workspace.activeClient);
