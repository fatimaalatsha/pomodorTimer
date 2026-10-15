"""
Rainbow Pomodoro - a translucent, always-on-top 60-minute visual timer.

Controls
  - Drag on the dial ............ set the time (like twisting the real timer)
  - Mouse wheel ................. +/- 1 minute
  - Click the purple knob ....... start / pause
  - Drag the purple rim ......... move the timer around the screen
  - Right-click ................. menu (lengths, opacity, size, pings, quit)
  - Space = start/pause, R = reset, N = skip, Ctrl+Q = quit
"""

import io
import json
import math
import os
import random
import struct
import threading
import time
import tkinter as tk
import wave
import winsound

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "pomodoro_settings.json")

KEY = "#010203"  # window colour that Windows renders fully transparent
BEZEL = "#B98CF0"
BEZEL_DARK = "#9563DA"
FACE = "#FFFFFF"
TICK = "#29A8E0"
RAINBOW = ["#E8202A", "#F7941D", "#FFD400", "#3DBE3A", "#1E90E8", "#3F3FBF", "#8E44C9"]
NUMBER_COLORS = ["#E8202A", "#F7941D", "#F2B705", "#2DB52A", "#16B8E0", "#3A2FB8"]

PHASES = {
    "focus": {"label": "FOCUS", "pill": "#1E9BE6"},
    "short": {"label": "BREAK", "pill": "#2DB52A"},
    "long": {"label": "LONG BREAK", "pill": "#8E44C9"},
}

DEFAULTS = {
    "focus": 25, "short": 5, "long": 15, "long_every": 4,
    "checkin": 0, "autostart": False, "opacity": 85, "size": 340,
    "topmost": True, "x": None, "y": None,
}

MESSAGES = {
    "focus": [
        ("Focus block done!", "Stand up, stretch, grab some water."),
        ("Nice work!", "You earned a break - look away from the screen."),
        ("Ding! Time's up", "Rest your eyes: look at something far away for 20 seconds."),
        ("Pomodoro complete", "Shoulders down, deep breath, short walk?"),
        ("Brilliant session", "Take your break - the work will still be here."),
    ],
    "short": [
        ("Break's over", "Ready for another focus round?"),
        ("Back to it!", "Pick one thing and give it your full attention."),
        ("Recharged?", "Click the knob to start the next focus block."),
    ],
    "long": [
        ("Long break finished", "Fresh cycle - let's go!"),
        ("Welcome back", "New set of pomodoros starting now."),
    ],
    "checkin": [
        ("Still going strong", "{m} minutes to go."),
        ("Quick check-in", "{m} min left - are you on task?"),
        ("Keep it up", "Only {m} minutes left in this block."),
    ],
}

# ----------------------------------------------------------------------------
# Random ping synthesiser (pure standard library)
# ----------------------------------------------------------------------------
RATE = 22050
SCALE = [523.25, 587.33, 659.25, 783.99, 880.00, 1046.50, 1174.66, 1318.51]
BELL = [(1.0, 1.0), (2.76, 0.35), (5.40, 0.12)]
SOFT = [(1.0, 1.0), (2.0, 0.25), (3.0, 0.08)]
WOOD = [(1.0, 1.0), (4.0, 0.25)]


def _render(events, total, loudness=0.8):
    n = int(total * RATE)
    buf = [0.0] * n
    attack = int(0.004 * RATE)
    for start, freq, dur, vol, partials, sweep in events:
        s0 = int(start * RATE)
        m = min(int(dur * RATE), n - s0)
        decay = 5.0 / dur
        two_pi_f = 2 * math.pi * freq
        for i in range(m):
            t = i / RATE
            env = math.exp(-decay * t) * (i / attack if i < attack else 1.0)
            ph = two_pi_f * (t + sweep * t * t / (2 * dur))
            v = 0.0
            for mult, amp in partials:
                v += amp * math.sin(ph * mult)
            buf[s0 + i] += vol * env * v
    peak = max(1e-9, max(abs(x) for x in buf))
    k = loudness * 32767 / peak
    frames = struct.pack("<%dh" % n, *(int(x * k) for x in buf))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    return out.getvalue()


def _ping_events(style):
    b = random.choice(SCALE[:5])
    if style == "bell":
        return [(0, b, 1.6, 1, BELL, 0)], 1.7
    if style == "chime_up":
        return [(i * 0.13, b * r, 1.0, 1, SOFT, 0) for i, r in enumerate((1, 1.25, 1.5, 2))], 1.5
    if style == "chime_down":
        return [(i * 0.13, b * r, 1.0, 1, SOFT, 0) for i, r in enumerate((2, 1.5, 1.25, 1))], 1.5
    if style == "ding_dong":
        return [(0, b * 1.5, 1.1, 1, BELL, 0), (0.38, b, 1.3, 1, BELL, 0)], 1.8
    if style == "marimba":
        return [(i * 0.11, b / 2 * r, 0.4, 1, WOOD, 0) for i, r in enumerate((1, 1.5, 2, 3))], 0.9
    if style == "sparkle":
        return [(i * 0.07, random.choice(SCALE[3:]) * 2, 0.45, 0.7, SOFT, 0) for i in range(7)], 1.0
    if style == "chirp":
        return [(0, b, 0.25, 1, SOFT, 0.6), (0.3, b * 1.25, 0.3, 1, SOFT, 0.6)], 0.7
    if style == "bubble":
        return [(i * 0.12, b * (1.5 - 0.15 * i), 0.18, 1, SOFT, -0.45) for i in range(4)], 0.7
    if style == "triple":
        return [(i * 0.22, b * 1.5, 0.5, 1, BELL, 0) for i in range(3)], 1.3
    raise ValueError(style)


PING_STYLES = ["bell", "chime_up", "chime_down", "ding_dong", "marimba",
               "sparkle", "chirp", "bubble", "triple"]
_last_style = None


def play_random_ping(loudness=0.8):
    """Play a different, randomly generated ping each call (non-blocking)."""
    global _last_style
    style = random.choice([s for s in PING_STYLES if s != _last_style])
    _last_style = style

    def worker():
        events, total = _ping_events(style)
        try:
            winsound.PlaySound(_render(events, total, loudness), winsound.SND_MEMORY)
        except RuntimeError:
            winsound.MessageBeep()

    threading.Thread(target=worker, daemon=True).start()


# ----------------------------------------------------------------------------
# Toast notification
# ----------------------------------------------------------------------------
class Toast:
    current = None

    def __init__(self, root, title, body, color, dpi):
        if Toast.current is not None:
            Toast.current.close()
        Toast.current = self
        w, h = int(340 * dpi), int(92 * dpi)
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.0)
        sx, sy = root.winfo_screenwidth(), root.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{sx - w - int(20 * dpi)}+{sy - h - int(70 * dpi)}")
        c = tk.Canvas(self.win, width=w, height=h, bg="#FFFFFF", highlightthickness=0, cursor="hand2")
        c.pack()
        c.create_rectangle(0, 0, w - 1, h - 1, outline="#D9C8F5", width=2)
        c.create_rectangle(0, 0, int(8 * dpi), h, fill=color, outline="")
        bar = int(16 * dpi)
        for i, col in enumerate(RAINBOW):
            c.create_rectangle(int(22 * dpi) + i * bar // 2, int(18 * dpi), int(22 * dpi) + (i + 1) * bar // 2,
                               int(22 * dpi), fill=col, outline="")
        c.create_text(int(22 * dpi), int(30 * dpi), anchor="nw", text=title, fill="#2B2B3A",
                      font=("Segoe UI", -int(18 * dpi), "bold"))
        c.create_text(int(22 * dpi), int(56 * dpi), anchor="nw", text=body, fill="#55556A",
                      width=w - int(34 * dpi), font=("Segoe UI", -int(13 * dpi)))
        c.bind("<Button-1>", lambda e: self.close())
        self.alive = True
        self._fade(0.0)
        self.win.after(10000, self.close)

    def _fade(self, a):
        if not self.alive:
            return
        a = min(0.96, a + 0.12)
        self.win.attributes("-alpha", a)
        if a < 0.96:
            self.win.after(25, self._fade, a)

    def close(self):
        if self.alive:
            self.alive = False
            self.win.destroy()
        if Toast.current is self:
            Toast.current = None


# ----------------------------------------------------------------------------
# Main app
# ----------------------------------------------------------------------------
class PomodoroApp:
    def __init__(self):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.cfg = dict(DEFAULTS)
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                self.cfg.update(json.load(f))
        except (OSError, ValueError):
            pass

        self.root = tk.Tk()
        self.root.title("Rainbow Pomodoro")
        self.dpi = self.root.winfo_fpixels("1i") / 96.0
        self.root.overrideredirect(True)
        self.root.configure(bg=KEY)
        self.root.attributes("-transparentcolor", KEY)
        self.root.attributes("-topmost", self.cfg["topmost"])
        self.root.attributes("-alpha", self.cfg["opacity"] / 100)

        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0)
        self.canvas.pack()

        # timer state
        self.phase = "focus"
        self.done_count = 0
        self.running = False
        self.started = False
        self.remaining = self.cfg["focus"] * 60.0
        self.end_time = 0.0
        self.since_checkin = 0.0
        self.last_tick = time.monotonic()
        self.last_drawn = None
        self.press = None
        self.last_dial_min = None

        self.apply_size(first=True)
        self.build_menu()

        c = self.canvas
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self.root.bind("<space>", lambda e: self.toggle())
        self.root.bind("<r>", lambda e: self.reset())
        self.root.bind("<n>", lambda e: self.skip())
        self.root.bind("<Control-q>", lambda e: self.quit())

        self.tick()

    # ---------------------------------------------------------------- geometry
    def apply_size(self, first=False):
        S = int(self.cfg["size"] * self.dpi)
        self.S = S
        self.c = S / 2
        self.R = S / 2 - 3
        self.Rf = self.R * 0.88
        self.canvas.config(width=S, height=S)
        x, y = self.cfg["x"], self.cfg["y"]
        if first and (x is None or y is None):
            x = self.root.winfo_screenwidth() - S - int(40 * self.dpi)
            y = int(60 * self.dpi)
        if x is None:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        self.root.geometry(f"{S}x{S}+{int(x)}+{int(y)}")
        self.draw_static()

    def polar(self, minutes, r):
        a = math.radians(minutes * 6)
        return self.c + r * math.sin(a), self.c - r * math.cos(a)

    # ----------------------------------------------------------------- drawing
    def draw_static(self):
        cv, c, R, Rf, S = self.canvas, self.c, self.R, self.Rf, self.S
        cv.delete("all")
        cv.create_oval(c - R, c - R, c + R, c + R, fill=BEZEL, outline=BEZEL_DARK, width=max(2, S // 120))
        hl = R * 0.96
        cv.create_arc(c - hl, c - hl, c + hl, c + hl, start=100, extent=70, style="arc",
                      outline="#D9C2FA", width=max(2, S // 70))
        cv.create_oval(c - Rf - 3, c - Rf - 3, c + Rf + 3, c + Rf + 3, fill=BEZEL_DARK, outline="")
        cv.create_oval(c - Rf, c - Rf, c + Rf, c + Rf, fill=FACE, outline="")

        for i in range(60):
            major = i % 5 == 0
            r1 = Rf * (0.64 if major else 0.69)
            x1, y1 = self.polar(i, r1)
            x2, y2 = self.polar(i, Rf * 0.74)
            cv.create_line(x1, y1, x2, y2, fill=TICK, width=max(1, S / (90 if major else 220)),
                           capstyle="round")

        fsize = -max(10, int(S * 0.062))
        for i in range(12):
            x, y = self.polar(i * 5, Rf * 0.86)
            cv.create_text(x, y, text=str(i * 5), fill=NUMBER_COLORS[i % 6],
                           font=("Segoe UI Black", fsize))
        self.last_drawn = None
        self.draw_dynamic()

    def current_remaining(self):
        if self.running:
            return max(0.0, self.end_time - time.monotonic())
        return self.remaining

    def draw_dynamic(self):
        cv, c, Rf, S = self.canvas, self.c, self.Rf, self.S
        rem = self.current_remaining()
        cv.delete("dyn")

        # rainbow wedge: remaining minutes, clockwise from 0
        extent = min(359.99, rem / 60.0 * 6.0)
        r_out, r_in = Rf * 0.615, Rf * 0.27
        band = (r_out - r_in) / len(RAINBOW)
        if extent > 0.05:
            for k, col in enumerate(RAINBOW):
                r = r_out - band * (k + 0.5)
                cv.create_arc(c - r, c - r, c + r, c + r, start=90, extent=-extent,
                              style="arc", outline=col, width=band + 1, tags="dyn")

        # time pill
        secs = int(math.ceil(rem))
        text = f"{secs // 60:02d}:{secs % 60:02d}"
        p = PHASES[self.phase]
        pw, ph = S * 0.30, S * 0.115
        py = c + Rf * 0.47
        x0, x1, y0, y1 = c - pw / 2, c + pw / 2, py - ph / 2, py + ph / 2
        rr = ph * 0.3
        cv.create_polygon(
            x0 + rr, y0, x1 - rr, y0, x1, y0, x1, y0 + rr, x1, y1 - rr, x1, y1, x1 - rr, y1,
            x0 + rr, y1, x0, y1, x0, y1 - rr, x0, y0 + rr, x0, y0,
            smooth=True, fill=p["pill"], outline="#FFFFFF", width=max(2, S // 140), tags="dyn")
        cv.create_text(c, py - ph * 0.14, text=text, fill="#FFFFFF",
                       font=("Segoe UI", -int(S * 0.058), "bold"), tags="dyn")
        every = self.cfg["long_every"]
        dots = "".join("●" if i < self.done_count % every else "○" for i in range(every))
        sub = p["label"] if self.phase != "focus" else f"FOCUS  {dots}"
        if not self.running and rem > 0:
            sub = "PAUSED" if self.started else sub
        cv.create_text(c, py + ph * 0.29, text=sub, fill="#FFFFFF",
                       font=("Segoe UI", -max(8, int(S * 0.027)), "bold"), tags="dyn")

        # knob
        kr = Rf * 0.19
        self.knob_r = kr
        off = kr * 0.12
        cv.create_oval(c - kr + off, c - kr + off * 1.5, c + kr + off, c + kr + off * 1.5,
                       fill="#D8D2E3", outline="", tags="dyn")
        cv.create_oval(c - kr, c - kr, c + kr, c + kr, fill="#A874EE", outline=BEZEL_DARK,
                       width=max(1, S // 170), tags="dyn")
        ki = kr * 0.74
        cv.create_oval(c - ki, c - ki, c + ki, c + ki, fill="#C49BF7", outline="", tags="dyn")
        ic = kr * 0.34
        icon = "#6A35B8"
        if self.running:
            w = ic * 0.38
            cv.create_rectangle(c - ic * 0.75, c - ic, c - ic * 0.75 + w, c + ic, fill=icon, outline="", tags="dyn")
            cv.create_rectangle(c + ic * 0.75 - w, c - ic, c + ic * 0.75, c + ic, fill=icon, outline="", tags="dyn")
        else:
            cv.create_polygon(c - ic * 0.6, c - ic, c - ic * 0.6, c + ic, c + ic * 1.0, c,
                              fill=icon, outline="", tags="dyn")

    # ------------------------------------------------------------------- timer
    def tick(self):
        now = time.monotonic()
        dt = now - self.last_tick
        self.last_tick = now
        if self.running:
            rem = self.end_time - now
            if self.phase == "focus" and self.cfg["checkin"]:
                self.since_checkin += dt
                if self.since_checkin >= self.cfg["checkin"] * 60 and rem > 45:
                    self.since_checkin = 0.0
                    title, body = random.choice(MESSAGES["checkin"])
                    self.notify(title, body.format(m=int(math.ceil(rem / 60))), loudness=0.45)
            if rem <= 0:
                self.finish()
        key = (int(math.ceil(self.current_remaining())), self.running, self.phase)
        if key != self.last_drawn:
            self.last_drawn = key
            self.draw_dynamic()
        self.root.after(200, self.tick)

    def set_remaining(self, secs):
        secs = max(0.0, min(3600.0, secs))
        if self.running:
            self.end_time = time.monotonic() + secs
        else:
            self.remaining = secs
        self.last_drawn = None
        self.draw_dynamic()

    def toggle(self):
        if self.running:
            self.remaining = self.current_remaining()
            self.running = False
        else:
            if self.remaining <= 0:
                return
            self.end_time = time.monotonic() + self.remaining
            self.running = True
            self.started = True
        self.last_drawn = None
        self.draw_dynamic()

    def load_phase(self, phase):
        self.phase = phase
        self.running = False
        self.started = False
        self.since_checkin = 0.0
        self.remaining = self.cfg[phase] * 60.0
        self.last_drawn = None
        self.draw_dynamic()

    def finish(self):
        ended = self.phase
        self.running = False
        self.remaining = 0
        title, body = random.choice(MESSAGES[ended])
        self.notify(title, body)
        if ended == "focus":
            self.done_count += 1
            nxt = "long" if self.done_count % self.cfg["long_every"] == 0 else "short"
        else:
            nxt = "focus"
        self.load_phase(nxt)
        if self.cfg["autostart"]:
            self.toggle()

    def skip(self):
        if self.phase == "focus":
            self.remaining, self.running = 0, False
            self.done_count += 1
            nxt = "long" if self.done_count % self.cfg["long_every"] == 0 else "short"
        else:
            nxt = "focus"
        self.load_phase(nxt)

    def reset(self):
        self.load_phase(self.phase)

    def notify(self, title, body, loudness=0.8):
        play_random_ping(loudness)
        Toast(self.root, title, body, PHASES[self.phase]["pill"], self.dpi)

    # ------------------------------------------------------------------- mouse
    def dial_minutes(self, x, y):
        dx, dy = x - self.c, y - self.c
        ang = (math.degrees(math.atan2(dx, -dy)) + 360) % 360
        m = round(ang / 6)
        last = self.last_dial_min
        if last is not None:
            if last >= 50 and m <= 10:
                m = 60
            elif last <= 10 and m >= 50 and last != 60:
                m = 0
            elif last == 60 and m <= 10:
                m = 60
        self.last_dial_min = m
        return m

    def on_press(self, e):
        self.root.focus_force()
        d = math.hypot(e.x - self.c, e.y - self.c)
        if d <= self.knob_r:
            self.press = "knob"
        elif d <= self.Rf:
            self.press = "dial"
            self.last_dial_min = None
            self.set_remaining(self.dial_minutes(e.x, e.y) * 60)
        else:
            self.press = "move"
            self.drag_off = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if self.press == "dial":
            self.set_remaining(self.dial_minutes(e.x, e.y) * 60)
        elif self.press == "move":
            self.root.geometry(f"+{e.x_root - self.drag_off[0]}+{e.y_root - self.drag_off[1]}")

    def on_release(self, e):
        if self.press == "knob" and math.hypot(e.x - self.c, e.y - self.c) <= self.knob_r:
            self.toggle()
        elif self.press == "move":
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
            self.save()
        self.press = None

    def on_wheel(self, e):
        rem = self.current_remaining()
        if e.delta > 0:
            self.set_remaining(math.floor(rem / 60) * 60 + 60)
        else:
            self.set_remaining(math.ceil(rem / 60) * 60 - 60)

    # -------------------------------------------------------------------- menu
    def build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Start / Pause    (Space)", command=self.toggle)
        m.add_command(label="Reset            (R)", command=self.reset)
        m.add_command(label="Skip to next     (N)", command=self.skip)
        m.add_separator()

        self.vars = {}

        def radio(label, key, options, fmt):
            sub = tk.Menu(m, tearoff=0)
            var = tk.IntVar(value=self.cfg[key])
            self.vars[key] = var
            for o in options:
                sub.add_radiobutton(label=fmt(o), value=o, variable=var,
                                    command=lambda k=key, v=var: self.set_cfg(k, v.get()))
            m.add_cascade(label=label, menu=sub)

        mins = lambda o: f"{o} min"
        radio("Focus length", "focus", [10, 15, 20, 25, 30, 40, 45, 50, 60], mins)
        radio("Short break", "short", [3, 5, 10, 15], mins)
        radio("Long break", "long", [10, 15, 20, 30], mins)
        radio("Long break every", "long_every", [2, 3, 4, 5, 6], lambda o: f"{o} pomodoros")
        radio("Check-in ping during focus", "checkin", [0, 5, 10, 15, 20],
              lambda o: "Off" if o == 0 else f"Every {o} min")
        self.auto_var = tk.BooleanVar(value=self.cfg["autostart"])
        m.add_checkbutton(label="Auto-start next session", variable=self.auto_var,
                          command=lambda: self.set_cfg("autostart", self.auto_var.get()))
        m.add_separator()
        radio("Size", "size", [240, 300, 340, 420, 520],
              lambda o: {240: "Tiny", 300: "Small", 340: "Medium", 420: "Large", 520: "Huge"}[o])
        radio("Opacity", "opacity", [100, 90, 85, 75, 60, 45, 30], lambda o: f"{o}%")
        self.top_var = tk.BooleanVar(value=self.cfg["topmost"])
        m.add_checkbutton(label="Always on top", variable=self.top_var,
                          command=lambda: self.set_cfg("topmost", self.top_var.get()))
        m.add_command(label="Test notification", command=lambda: self.notify(*random.choice(MESSAGES["focus"])))
        m.add_separator()
        m.add_command(label="Quit    (Ctrl+Q)", command=self.quit)
        self.menu = m

    def set_cfg(self, key, value):
        self.cfg[key] = value
        if key == self.phase and not self.started:
            self.remaining = value * 60.0
        if key == "opacity":
            self.root.attributes("-alpha", value / 100)
        elif key == "topmost":
            self.root.attributes("-topmost", value)
        elif key == "size":
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
            self.apply_size()
        self.last_drawn = None
        self.draw_dynamic()
        self.save()

    def save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
        except OSError:
            pass

    def quit(self):
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        self.save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    PomodoroApp().run()
