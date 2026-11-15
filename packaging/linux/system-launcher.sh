#!/bin/sh
# Installed Debian-package entry point. The engine owns its session lifecycle.
exec /opt/cimc-studio/CIMC-Engine --desktop "$@"
