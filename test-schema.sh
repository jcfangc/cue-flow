#!/bin/sh
set -eu

cue vet -c=false ./examples/request_response.cue

if cue vet -c=false ./testdata/invalid_close.cue; then
	echo "expected invalid close value to be rejected" >&2
	exit 1
fi

if cue vet -c=false ./testdata/invalid_message_value.cue; then
	echo "expected message value outside the registered CUE constraint to be rejected" >&2
	exit 1
fi

if cue vet -c ./testdata/missing_required.cue; then
	echo "expected missing required protocol fields to be rejected" >&2
	exit 1
fi
