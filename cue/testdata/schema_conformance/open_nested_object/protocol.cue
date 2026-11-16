package open_nested_object

import flow "github.com/jcfangc/cue-flow:cueflow"

#Request: {
	id:       string
	metadata: {label?: string, ...}
}

protocol: flow.#Protocol & {
	messages: {Request: #Request}
	initial: "Ready"
	states: {
		Ready: {recv: {Request: "Done"}}
		Done:  {}
	}
}
