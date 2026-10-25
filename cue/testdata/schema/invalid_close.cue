package testdata

import flow "github.com/jcfangc/cue-flow:cueflow"

protocol: flow.#Protocol & {
	messages: {}
	initial: "Ready"
	states: {
		Ready: {
			close: true
		}
	}
}
