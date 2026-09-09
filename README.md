# use-blender

Blender in a Docker container, ready for computer-use agents. Take screenshots,
send mouse and keyboard input, and optionally execute Python through a small REST API.

Uses software rendering, so no GPU is required. No video streaming or bundled agent framework.

## Get started

Requires Docker. Build directly from GitHub and start Blender:

```sh
docker build -t use-blender 'https://github.com/shhivv/use-blender.git#master'
docker run -d --name use-blender -p 127.0.0.1:8765:8000 use-blender
```

Once Blender is ready:

```sh
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/screenshot -o blender.png
```

The image is built locally; there is no registry image to install.

## Use the API

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Check readiness, version, and screen size |
| `GET /screenshot` | Capture the desktop as PNG |
| `GET /state` | Get session metadata; includes scene details when Python is enabled |
| `POST /actions` | Send mouse and keyboard actions |
| `POST /python` | Run Python in the live Blender session (opt-in) |

For example, move the selected cube two units along X:

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
```

Actions include `move`, `click`, `drag`, `scroll`, `key`, `text`, `mouse_down`,
`mouse_up`, `key_down`, `key_up`, `release`, and `wait`. Coordinates match the
screenshot, starting at the top left. Move the pointer over the intended Blender
editor before sending shortcuts, then inspect a new screenshot to check the result.

To enable Python, add `-e ENABLE_PYTHON=1` before the image name in the
`docker run` command above. You can then save and retrieve a Blender file:

```sh
curl http://127.0.0.1:8765/python \
  -H 'Content-Type: application/json' \
  -d '{"code":"bpy.ops.wm.save_as_mainfile(filepath=\"/workspace/model.blend\")"}'

docker cp use-blender:/workspace/model.blend ./model.blend
```

`bpy` is available automatically. Set `result` to return a JSON value. Keep scripts
short: they run on Blender's main thread, and a timeout does not undo or stop them.

## Configuration

Default resolution: **1280×800**. The command above exposes the API on port **8765**.
Pass environment variables with `docker run -e`, such as `-e RESOLUTION=1600x1000`.
Change the host port in `-p` if needed. The API binds to localhost; set `API_TOKEN`
to require bearer authentication.
Only connect trusted clients, since Blender also exposes its own Python console.

Optionally add `--cpus=2 --memory=4g` to limit resources, or
`-v use-blender-workspace:/workspace` to reuse saved files across container replacements.
`docker restart use-blender` starts a fresh scene; `docker stop use-blender`
stops the service and keeps saved files.

Includes Blender **5.0.1**. Tested on **Linux ARM64** through OrbStack;
AMD64 has not yet been validated.

## Need managed scale?

Built by [Isle](https://www.tryisle.com). Isle provides managed application
environments for computer-use agents, with infrastructure to deploy and scale
them. Run this project yourself, or use Isle when you want the infrastructure
managed for you.

## License

[MIT](LICENSE) for this project's code. Blender and system dependencies retain
their own licenses; see [third-party notices](THIRD_PARTY.md).
