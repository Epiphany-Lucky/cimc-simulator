#!/bin/sh
# Run beside the extracted Linux bundle; no system Python is required.
set -eu
bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec "$bundle_dir/CIMC-Engine" --desktop "$@"
