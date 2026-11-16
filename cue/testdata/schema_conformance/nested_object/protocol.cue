package nested_object

import flow "github.com/jcfangc/cue-flow:cueflow"

#QueryFilter: {
	sequence: string & =~"^[ACGT]+$"
	note?:    string
	range: {
		topK:   int & >=1 & <=100
		active: bool
	}
}

#Query: {
	id:     string & !=""
	filter: #QueryFilter
	"filter.sequence": string & !=""
	wire: {
		"route/path": string & !=""
	}
	"wire/route/path": string & !=""
	"wire~1name":    string & !=""
	"wire/name":     string & !=""
	details?: {
		label: string & !=""
	}
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
			recv: {Query: "Waiting"}
		}
		Waiting: {
			send: {Result: "Ready"}
		}
	}
}

sample: {
	query: protocol.messages.Query & {
		id: "q1"
		"filter.sequence": "root-level"
		"wire/route/path": "root-slash"
		"wire~1name": "tilde"
		"wire/name": "slash"
		filter: {
			sequence: "ACGT"
			range: {
				topK: 5
				active: true
			}
		}
		wire: {"route/path": "nested-slash"}
	}
}
