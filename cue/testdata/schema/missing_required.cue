package testdata

import flow "github.com/jcfangc/cue-flow:cueflow"

protocol: flow.#Protocol & {
	initial: "Ready"
}
