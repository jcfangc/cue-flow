package unsupported

import flow "github.com/jcfangc/cue-flow:cueflow"

#Mode: "fast" | "safe"

protocol: flow.#Protocol & {
	messages: {
		Mode: #Mode
	}
	initial: "Ready"
	states: {
		Ready: {
			recv: {
				Mode: "Ready"
			}
		}
	}
}
