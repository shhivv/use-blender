"""One X11 connection for screenshots and real XTEST input; no polling loop."""
import io
import math
import subprocess
import time

from PIL import Image
from Xlib import X, XK, display
from Xlib.ext import xtest

BUTTONS = {"left": 1, "middle": 2, "right": 3}
KEYS = {
    "ctrl": "Control_L", "control": "Control_L", "shift": "Shift_L",
    "alt": "Alt_L", "super": "Super_L", "enter": "Return",
    "esc": "Escape", "escape": "Escape", "space": "space",
    "tab": "Tab", "backspace": "BackSpace", "delete": "Delete",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
    "num0": "KP_0", "num1": "KP_1", "num2": "KP_2", "num3": "KP_3",
    "num4": "KP_4", "num5": "KP_5", "num6": "KP_6", "num7": "KP_7",
    "num8": "KP_8", "num9": "KP_9", "decimal": "KP_Decimal",
}
FIELDS = {
    "move": {"x", "y"}, "click": {"x", "y", "button", "count"},
    "mouse_down": {"button"}, "mouse_up": {"button"},
    "key": {"key", "modifiers"}, "key_down": {"key"}, "key_up": {"key"},
    "text": {"text"}, "scroll": {"direction", "steps", "x", "y"},
    "drag": {"from_x", "from_y", "to_x", "to_y", "button", "modifiers", "duration"},
    "wait": {"seconds"}, "release": set(),
}


class Desktop:
    def __init__(self):
        self.d = display.Display()
        self.root = self.d.screen().root
        self.width = self.d.screen().width_in_pixels
        self.height = self.d.screen().height_in_pixels
        self.keys, self.buttons = set(), set()

    def keycode(self, key):
        if not isinstance(key, str):
            raise ValueError("key must be a string")
        name = KEYS.get(key.lower(), key)
        if key.lower().startswith("f") and key[1:].isdigit():
            name = key.upper()
        code = self.d.keysym_to_keycode(XK.string_to_keysym(name))
        if not code:
            raise ValueError(f"Unknown key: {key}. Use text for characters and key for shortcuts.")
        return code

    def validate(self, actions):
        if not isinstance(actions, list) or not 1 <= len(actions) <= 64:
            raise ValueError("actions must contain 1..64 actions")
        total_time = 0
        for a in actions:
            if not isinstance(a, dict) or not isinstance(a.get("type"), str):
                raise ValueError("Each action needs a type")
            kind = a["type"]
            if kind not in FIELDS or set(a) - FIELDS[kind] - {"type"}:
                raise ValueError(f"Unknown action or fields: {kind}")
            for field, limit in (("x", self.width), ("y", self.height),
                                 ("from_x", self.width), ("from_y", self.height),
                                 ("to_x", self.width), ("to_y", self.height)):
                if field in a and (type(a[field]) is not int or not 0 <= a[field] < limit):
                    raise ValueError(f"{field} must be an integer within the screenshot")
            if kind in {"move", "click"} and not {"x", "y"} <= a.keys():
                raise ValueError("move/click require x and y")
            if kind == "scroll" and (("x" in a) != ("y" in a)):
                raise ValueError("Provide both x and y")
            if kind == "drag" and not {"from_x", "from_y", "to_x", "to_y"} <= a.keys():
                raise ValueError("drag requires from_x, from_y, to_x, to_y")
            if a.get("button", "left") not in BUTTONS:
                raise ValueError("button must be left, middle, or right")
            if kind in {"key", "key_down", "key_up"}:
                self.keycode(a.get("key"))
            modifiers = a.get("modifiers", [])
            if not isinstance(modifiers, list) or any(m not in {"ctrl", "alt", "shift", "super"} for m in modifiers):
                raise ValueError("modifiers must be a list of ctrl, alt, shift, super")
            if kind == "text" and (not isinstance(a.get("text"), str) or len(a["text"]) > 4096 or "\x00" in a["text"]):
                raise ValueError("text must be a string of at most 4096 characters without NUL")
            for field, default, maximum in (("count", 1, 3), ("steps", 1, 20)):
                value = a.get(field, default)
                if type(value) is not int or not 1 <= value <= maximum:
                    raise ValueError(f"{field} must be 1..{maximum}")
            if kind == "scroll" and a.get("direction") not in {"up", "down", "left", "right"}:
                raise ValueError("scroll requires direction: up, down, left, or right")
            for field, default, maximum in (("duration", 0.3, 3), ("seconds", 0.1, 5)):
                value = a.get(field, default)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
                    raise ValueError(f"{field} must be between 0 and {maximum}")
            total_time += a.get("seconds", 0.1) if kind == "wait" else a.get("duration", 0.3) if kind == "drag" else 0.1
        if total_time > 15:
            raise ValueError("Action batch is too long; split it into shorter batches")

    def move(self, x, y):
        xtest.fake_input(self.d, X.MotionNotify, x=x, y=y)
        self.d.sync()

    def button(self, button, down):
        code = BUTTONS[button]
        xtest.fake_input(self.d, X.ButtonPress if down else X.ButtonRelease, code)
        (self.buttons.add if down else self.buttons.discard)(code)
        self.d.sync()

    def key(self, name, down):
        code = self.keycode(name)
        xtest.fake_input(self.d, X.KeyPress if down else X.KeyRelease, code)
        (self.keys.add if down else self.keys.discard)(code)
        self.d.sync()

    def press(self, key, modifiers=()):
        added = [m for m in modifiers if self.keycode(m) not in self.keys]
        try:
            for modifier in added:
                self.key(modifier, True)
            self.key(key, True)
            self.key(key, False)
        finally:
            for modifier in reversed(added):
                self.key(modifier, False)

    def release(self):
        for code in list(self.keys):
            xtest.fake_input(self.d, X.KeyRelease, code)
        for code in list(self.buttons):
            xtest.fake_input(self.d, X.ButtonRelease, code)
        self.keys.clear()
        self.buttons.clear()
        self.d.sync()

    def act(self, a):
        kind = a["type"]
        if kind in {"move", "click", "scroll"} and "x" in a:
            self.move(a["x"], a["y"])
        if kind == "click":
            for _ in range(a.get("count", 1)):
                self.button(a.get("button", "left"), True)
                self.button(a.get("button", "left"), False)
                time.sleep(0.04)
        elif kind in {"mouse_down", "mouse_up"}:
            self.button(a.get("button", "left"), kind == "mouse_down")
        elif kind == "key":
            self.press(a["key"], a.get("modifiers", []))
        elif kind in {"key_down", "key_up"}:
            self.key(a["key"], kind == "key_down")
        elif kind == "text":
            # Clipboard paste handles Unicode independently of the keyboard map.
            subprocess.run(["xclip", "-selection", "clipboard", "-in"],
                           input=a["text"].encode(), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True, timeout=3)
            self.press("v", ["ctrl"])
        elif kind == "scroll":
            code = {"up": 4, "down": 5, "left": 6, "right": 7}[a["direction"]]
            for _ in range(a.get("steps", 1)):
                xtest.fake_input(self.d, X.ButtonPress, code)
                xtest.fake_input(self.d, X.ButtonRelease, code)
        elif kind == "drag":
            mods = [m for m in a.get("modifiers", []) if self.keycode(m) not in self.keys]
            button = a.get("button", "left")
            self.move(a["from_x"], a["from_y"])
            try:
                for m in mods:
                    self.key(m, True)
                self.button(button, True)
                duration = a.get("duration", 0.3)
                steps = max(2, round(duration * 60))
                for i in range(1, steps + 1):
                    self.move(round(a["from_x"] + (a["to_x"]-a["from_x"])*i/steps),
                              round(a["from_y"] + (a["to_y"]-a["from_y"])*i/steps))
                    time.sleep(duration / steps)
            finally:
                self.button(button, False)
                for m in reversed(mods):
                    self.key(m, False)
        elif kind == "wait":
            time.sleep(a.get("seconds", 0.1))
        elif kind == "release":
            self.release()
        self.d.sync()
        if kind not in {"wait", "drag"}:
            time.sleep(0.05)

    def screenshot(self):
        self.d.sync()
        pixels = self.root.get_image(0, 0, self.width, self.height, X.ZPixmap, 0xFFFFFFFF)
        image = Image.frombytes("RGB", (self.width, self.height), pixels.data, "raw", "BGRX")
        out = io.BytesIO()
        image.save(out, format="PNG", compress_level=1)
        return out.getvalue()
