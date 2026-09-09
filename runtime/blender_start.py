"""Blender defaults and a local main-thread bridge. No third-party add-on."""
import contextlib
import io
import json
import os
import socket
import traceback

import bpy
import gpu

ROOT = "/tmp/use-blender"
prefs = bpy.context.preferences
prefs.view.show_splash = False
prefs.view.smooth_view = 0
prefs.view.language = "en_US"
prefs.view.use_translate_interface = False
prefs.filepaths.use_load_ui = False
prefs.edit.undo_memory_limit = 256
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.shading.type = "SOLID"

SERVER = socket.socket(socket.AF_UNIX)
SERVER.bind(ROOT + "/bridge.sock")
SERVER.listen(4)
SERVER.setblocking(False)
CLIENTS = {}
NAMESPACE = {"bpy": bpy, "__name__": "__use_blender__"}


class Output(io.StringIO):
    def write(self, value):
        return super().write(value[:max(0, 32768-self.tell())])


def scene_state():
    active = bpy.context.view_layer.objects.active
    return {
        "blender_version": bpy.app.version_string,
        "file": bpy.data.filepath,
        "mode": bpy.context.mode,
        "active_object": active.name if active else None,
        "selected": [o.name for o in bpy.context.selected_objects],
        "object_count": len(bpy.context.scene.objects),
        "renderer": gpu.platform.renderer_get(),
    }


def dispatch(message):
    bpy.context.view_layer.update()
    if message.get("type") == "inspect":
        return scene_state()
    if message.get("type") != "python":
        raise ValueError("Unknown bridge operation")
    output = Output()
    NAMESPACE.pop("result", None)
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exec(compile(message["code"], "<use-blender>", "exec"), NAMESPACE)
        value = NAMESPACE.get("result")
        if len(json.dumps(value, allow_nan=False)) > 131072:
            raise ValueError("Result too large")
        result = {"status": "succeeded", "result": value}
    except Exception:
        result = {"status": "failed", "error": traceback.format_exc(limit=5)}
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    return {**result, "stdout": output.getvalue()}


def tick():
    try:
        client, _ = SERVER.accept()
        client.setblocking(False)
        if len(CLIENTS) < 4:
            CLIENTS[client] = bytearray()
        else:
            client.close()
    except BlockingIOError:
        pass
    for client, data in list(CLIENTS.items()):
        try:
            chunk = client.recv(65536)
            if not chunk:
                raise ConnectionError()
            data.extend(chunk)
            if len(data) > 131072:
                raise ConnectionError()
            if b"\n" not in data:
                continue
            response = dispatch(json.loads(data.split(b"\n", 1)[0]))
            client.settimeout(1)
            client.sendall(json.dumps(response, allow_nan=False).encode()+b"\n")
        except BlockingIOError:
            continue
        except Exception as error:
            print("Bridge:", str(error), flush=True)
        client.close()
        CLIENTS.pop(client, None)
    return 0.03


bpy.app.timers.register(tick, first_interval=0.1, persistent=True)
print("use-blender: bridge ready", flush=True)
