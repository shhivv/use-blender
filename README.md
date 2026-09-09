# use-blender

**Run Blender in a container. Control it over HTTP.**

One persistent Blender desktop, PNG screenshots, mouse and keyboard input, and
an optional Python endpoint. Runs locally with Docker, without an account or
external service. No video streaming or model runtime.

## Start

From this repository:

```sh
docker compose up --build -d
curl http://127.0.0.1:8765/health
```

The first build downloads Blender and its system dependencies. Once healthy,
take a screenshot:

```sh
curl http://127.0.0.1:8765/screenshot -o blender.png
```

Or build and run the image directly:

```sh
docker build -t use-blender:latest .
docker run --rm --name use-blender --shm-size=256m \
  --cpus=2 --memory=4g \
  -p 127.0.0.1:8765:8000 \
  -v blender-workspace:/workspace \
  use-blender:latest
```

`use-blender:latest` is a local image tag. This repository does not assume a
published registry image.

## Control Blender

Move the selected cube two units along X:

```sh
curl http://127.0.0.1:8765/actions \
  -H 'Content-Type: application/json' \
  -d '{"actions":[
    {"type":"move","x":500,"y":350},
    {"type":"key","key":"g"},
    {"type":"key","key":"x"},
    {"type":"key","key":"2"},
    {"type":"key","key":"enter"}
  ]}'

curl http://127.0.0.1:8765/screenshot -o moved.png
```

Coordinates refer directly to the returned screenshot, with the origin at the
top left. Move the pointer over the intended Blender editor before using its
shortcuts. Modifier keys and modes behave like normal Blender.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Readiness, Blender version, renderer, resolution, session ID |
| `GET /state` | Same metadata; adds scene information when Python is enabled |
| `GET /screenshot` | Current desktop as PNG, captured on demand |
| `POST /actions` | An ordered batch of mouse/keyboard actions |
| `POST /python` | Execute Python in the live Blender process; opt-in |

All POST bodies are JSON. Successful actions return `status: "delivered"`.
That means the input was sent, not that Blender has completed the intended
operation. Inspect a screenshot after each short batch. Complex operations may
need another observation or an explicit `wait` action. PNG responses include
`X-Width`, `X-Height`, `X-Captured-At-Ns`, and `X-Session-ID` headers.

### Actions

Each example below is one item in the `actions` array:

```json
{"type":"move","x":500,"y":350}
{"type":"click","x":500,"y":350,"button":"left","count":1}
{"type":"drag","from_x":500,"from_y":350,"to_x":600,"to_y":400,"button":"middle","duration":0.3}
{"type":"drag","from_x":500,"from_y":350,"to_x":600,"to_y":400,"button":"middle","modifiers":["shift"]}
{"type":"scroll","direction":"up","steps":3,"x":500,"y":350}
{"type":"key","key":"s","modifiers":["ctrl"]}
{"type":"key","key":"num1"}
{"type":"text","text":"Cube café Ω"}
{"type":"mouse_down","button":"left"}
{"type":"key_down","key":"shift"}
{"type":"key_up","key":"shift"}
{"type":"mouse_up","button":"left"}
{"type":"release"}
{"type":"wait","seconds":0.5}
```

`text` pastes through the clipboard into the currently focused text field.
Use `key` for shortcuts or numerical transform input. Key aliases include
`ctrl`, `alt`, `shift`, `super`, `enter`, `escape`, `space`, `tab`, `backspace`,
`delete`, arrow keys, `f1`–`f12`, and `num0`–`num9`. X11 key names also work.
Buttons are `left`, `middle`, and `right`; scrolling supports all four directions.

`key_down` and `mouse_down` remain held between requests until released. Prefer
the complete `drag`/`key` actions for common gestures. `release` releases keys and
buttons held by the API; send Escape separately if you want to cancel a Blender
modal operation.

The server accepts one mutation at a time and returns 409 while busy. It does
not retry actions automatically and does not deduplicate requests. If a response
is lost, inspect the desktop before deciding what to do next.

## Optional Python

Enable Python when you want programmatic scene editing in the same session:

```sh
ENABLE_PYTHON=1 docker compose up -d

curl http://127.0.0.1:8765/python \
  -H 'Content-Type: application/json' \
  -d '{"code":"bpy.ops.mesh.primitive_monkey_add(); result = bpy.context.object.name"}'
```

`bpy` is available in a persistent namespace. Set `result` to a JSON-serializable
value to return it. The response also contains `stdout` and a success/failure
status. Prefer short scripts and Blender's data API where possible.

Save and reopen:

```sh
curl http://127.0.0.1:8765/python \
  -H 'Content-Type: application/json' \
  -d '{"code":"bpy.ops.wm.save_as_mainfile(filepath=\"/workspace/model.blend\")"}'

docker compose cp blender:/workspace/model.blend ./model.blend

curl http://127.0.0.1:8765/python \
  -H 'Content-Type: application/json' \
  -d '{"code":"bpy.ops.wm.open_mainfile(filepath=\"/workspace/model.blend\", load_ui=False)"}'
```

Scripts run on Blender's main thread. Errors can leave partial changes. A
30-second timeout does not cancel accepted code: the API blocks further mutations
until the container is restarted, so an uncertain script cannot overlap new
input. Long final renders are better run as separate Blender batch jobs.

## Files and lifecycle

The named `/workspace` volume persists saved files across container replacements.
Use `docker compose cp` to move assets in or outputs out. A bind mount also works;
its directory must be writable by container UID **10001**.

`docker compose restart` starts a fresh default scene. Saved files remain in the
volume and can be reopened; unsaved edits and the Python namespace are lost.
The session ID changes on each restart. `docker compose down` stops the service
and preserves the volume. Adding `-v` also deletes the volume.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `BLENDER_PORT` | `8765` | Host port published by Compose |
| `RESOLUTION` | `1280x800` | Fixed desktop size; 640×480 through 2560×1600 |
| `ENABLE_PYTHON` | `0` | Enable arbitrary Python execution and scene metadata |
| `API_TOKEN` | unset | Require `Authorization: Bearer …` on every endpoint |
| `LP_NUM_THREADS` | `2` | CPU threads used by Mesa software rendering |
| `PORT` | `8000` | Container HTTP port; adjust Docker port mapping if changed |

Compose exposes the API at `http://127.0.0.1:8765`. To use a different host
port, run `BLENDER_PORT=9000 docker compose up -d` and use port 9000 in requests.
If you receive `{"detail":"Not Found"}`, check that you are contacting the correct
port: another local server may already occupy a common port such as 8000.

Compose exposes the API on localhost. The API controls the whole Blender desktop;
disabling `/python` does not prevent code execution through Blender's own console.
Use only trusted clients, and set `API_TOKEN` if exposing it beyond localhost.
This container is an application runtime, not a boundary for hostile agent code.

## What's inside

- Ubuntu 26.04 base pinned by digest, Blender **5.0.1** pinned by package version.
- Xvfb + Openbox, Mesa LLVMpipe software rendering; no GPU setup required.
- Python standard-library HTTP server, Python-Xlib/XTEST, Pillow, and xclip.
- Tini for process reaping; container runs as a non-root user.
- Stock Blender interface, Solid viewport, disabled view animation and splash,
  bounded undo memory, and no audio service.

There is no Isle dependency, model SDK, browser, video encoder, desktop suite,
database, or account system. The Ubuntu Blender package was selected for native
ARM64 and AMD64 availability. **The working image has been tested on ARM64 in
OrbStack; AMD64 and GPU acceleration have not been validated.** This initial
release is intended for modeling and light scenes with software rendering.

## License

The original runtime code in this repository is MIT licensed. Blender and the
system packages retain their own licenses. See [THIRD_PARTY.md](THIRD_PARTY.md).
