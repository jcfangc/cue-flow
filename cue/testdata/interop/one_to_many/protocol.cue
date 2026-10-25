package interop

import flow "github.com/jcfangc/cue-flow:cueflow"

#Query: {
	id: string & !=""
}

#Result: {
	id:     string & !=""
	result: string
}

protocol: flow.#Protocol & {
	messages: {
		Query:  #Query
		Result: #Result
	}
	initial: "Ready"
	states: {
		Ready: {
			recv: {Query: "Streaming"}
		}
		Streaming: {
			send: {Result: "Streaming"}
		}
	}
}
