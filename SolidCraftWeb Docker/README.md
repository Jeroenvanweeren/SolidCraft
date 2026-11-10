# SolidCraft web container

This folder runs the official SolidCraft browser release in nginx and adds a small, authenticated
endpoint for installing published web releases. It does not build or modify the SolidCraft source
repository. Release ZIP files are checked against the release's `SHA256SUMS.txt` before activation.

## Start

Docker Compose downloads the newest stable web release on first start and stores it in a named
volume. Set a long random token before starting:

```sh
cd "SolidCraftWeb Docker"
export SOLIDCRAFT_UPDATE_TOKEN="$(openssl rand -hex 32)"
docker compose up -d --build
```

## Published container images

Releases are published to `ghcr.io/jeroenvanweeren/solidcraft-web`. To run a published version,
choose its image tag and start Compose without building locally:

```sh
export SOLIDCRAFT_IMAGE_TAG=1.2.3
docker compose pull
docker compose up -d
```

Replace `1.2.3` with a published version; `latest` tracks the newest stable release. Each stable
release also publishes `MAJOR.MINOR` and `MAJOR` tags. Pre-releases receive only their exact
version tag and are marked as pre-releases on GitHub.

To publish a release, push a SemVer tag beginning with `v`, for example `v1.2.3`. GitHub Actions
runs the updater tests, downloads and verifies the SolidCraft web bundle, builds and pushes the
image, then creates a GitHub Release with generated release notes. The workflow uses the repository's
`GITHUB_TOKEN`; no registry password or email secret is needed. On the first successful publish,
open the `solidcraft-web` package settings on GitHub and change its visibility to **Public** if
you want unauthenticated pulls.

```sh
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3
```

Open `http://localhost:8080/`. For a remote deployment, put HTTPS in front of the container;
SolidCraft needs a secure browser context to save designs. Do not expose the update endpoint over
an untrusted plain-HTTP network.

## Deploy latest and restart

From the repository root, run the deployment script:

```sh
bash "SolidCraftWeb Docker/deploy.sh"
```

On first run, the script generates a random bearer token and stores it in the ignored,
owner-readable `.update-token` file in this folder. You can instead provide your own token through
`SOLIDCRAFT_UPDATE_TOKEN`.

The script runs the full updater test suite and validates Compose first. It then updates the
persisted web release, copies that release into the image build, stops the service, rebuilds the
container image, verifies that the bundle is in the image, and starts a fresh container. If the
rebuild fails after stopping the service, it attempts to restart the previous container. The
`solidcraft-data` volume remains authoritative at runtime, so rebuilding the image does not discard
the installed release.

## Update API

The API is on the same origin as the app and requires the configured bearer token.

```sh
curl -X POST \
  -H "Authorization: Bearer $SOLIDCRAFT_UPDATE_TOKEN" \
  http://localhost:8080/_admin/update
```

With no `version` parameter, the endpoint checks the latest stable GitHub release and installs it
only if it differs from the active release. Pin a specific release with:

```sh
curl -X POST \
  -H "Authorization: Bearer $SOLIDCRAFT_UPDATE_TOKEN" \
  'http://localhost:8080/_admin/update?version=0.30.1'
```

Versions may include the leading `v`; an explicitly requested published release candidate is also
accepted, for example `version=0.31.0-rc.2`. The current version can be read with the authenticated
`GET /_admin/status` endpoint. A successful update returns JSON with `version` and `updated` fields.

The update is downloaded to a temporary directory, checksum-verified, safely extracted, and made
active by atomically replacing a symlink. An unsuccessful update leaves the current version in
place. The API does not poll in the background; call the update endpoint whenever you want it to
check GitHub.

## Configuration

- `SOLIDCRAFT_PORT`: host port, default `8080`.
- `SOLIDCRAFT_UPDATE_TOKEN`: required bearer token, at least 32 characters.
- `solidcraft-data`: named volume containing installed releases and the active-version symlink.

The API listens only on the container's loopback interface; nginx proxies `/_admin/` to it. The
container runs as an unprivileged user with a read-only root filesystem and no Linux capabilities.

## Tests

Run the updater unit tests with:

```sh
python3 -m unittest test_updater.py
```