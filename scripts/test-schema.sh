#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root/cue"

cue vet -c=false ./examples/request_response.cue

if cue vet -c=false ./testdata/schema/invalid_close.cue; then
	echo "expected removed explicit close field to be rejected" >&2
	exit 1
fi

if cue vet -c=false ./testdata/schema/invalid_message_value.cue; then
	echo "expected message value outside the registered CUE constraint to be rejected" >&2
	exit 1
fi

if cue vet -c ./testdata/schema/missing_required.cue; then
	echo "expected missing required protocol fields to be rejected" >&2
	exit 1
fi
