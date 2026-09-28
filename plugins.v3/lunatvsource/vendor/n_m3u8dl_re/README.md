# N_m3u8DL-RE bundled release archives

LunaTVSource redistributes the official `v0.5.1-beta` Linux release archives
under the upstream MIT license so a MoviePilot NAS can install the pinned
engine without reaching GitHub during first use.

- Upstream: https://github.com/nilaoda/N_m3u8DL-RE
- Release: https://github.com/nilaoda/N_m3u8DL-RE/releases/tag/v0.5.1-beta
- Linux x64 archive SHA-256: `2acce91b64af3ee676a32d1002e1382840d81f430e1b7f8d5b151ce1eb6fb590`
- Linux arm64 archive SHA-256: `b9cce9978e94fd8ce509ee86a6543cccffeb0ee5b7b7aeff1314104265ac65ad`

The plugin verifies the archive and extracted executable against pinned
SHA-256 values before installing it into the plugin data directory. If the
matching bundled archive is absent, the installer may fetch the same pinned
official GitHub release as a fallback.
