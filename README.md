# CaelestiaPlugin-OpenRGB

Optional hardware RGB lighting for Caelestia, intentionally split from `CaelestiaPlugin-Color`.

Features:
- follow the live Caelestia accent
- custom solid colour
- real OpenRGB profiles
- per-controller enable/disable
- hardware brightness only where the controller reports support
- restore state at login through a user service

State is kept in `~/.config/caelestia/rgb.json`; device-specific exclusions are not part of Color synchronization.

## Dependencies

Install the system `openrgb` package (and `i2c-tools` where motherboard/RAM access is needed), then run `./install.sh`. The installer creates a small private Python venv for `openrgb-python`, installs the localhost SDK server unit and enables restore-on-login.
