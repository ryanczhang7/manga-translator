#!/usr/bin/env bash
# Start the project in development mode (see project.conf).
exec bash "$(dirname "${BASH_SOURCE[0]}")/task.sh" dev "$@"
