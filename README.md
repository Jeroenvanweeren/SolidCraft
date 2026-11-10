# SolidCraft Web Container

A managed web container for the SolidCraft browser release. The container installs verified
upstream web releases and serves them through an unprivileged nginx process.

## Run a published version

```sh
docker pull ghcr.io/jeroenvanweeren/solidcraft-web:1.0.0
```

The stable `1.0` and `1` tags track the latest compatible release in those version lines; `latest`
tracks the newest stable release. Published versions are also available from the
[GitHub Container Registry](https://github.com/Jeroenvanweeren/SolidCraft/pkgs/container/solidcraft-web).

For Compose setup, update configuration, and release instructions, see
[SolidCraftWeb Docker/README.md](SolidCraftWeb%20Docker/README.md).