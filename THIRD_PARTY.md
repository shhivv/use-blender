# Third-party software

The repository's MIT license covers its original runtime and documentation. It
does not relicense Blender, Ubuntu, or their dependencies.

Blender is installed unmodified from Ubuntu's `blender` package. Its license and
the package's source references are at:

- https://www.blender.org/about/license/
- https://packages.ubuntu.com/resolute/blender

The image retains package copyright and license notices under
`/usr/share/doc/*/copyright`. The package version is pinned in the Dockerfile;
the installed package inventory can be obtained with:

```sh
docker run --rm --entrypoint dpkg-query use-blender:latest -W
```

This project is distributed as source. The Dockerfile builds the image locally.
