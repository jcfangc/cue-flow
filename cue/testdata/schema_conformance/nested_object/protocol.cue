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
		filter: {
			sequence: "ACGT"
			range: {
				topK: 5
				active: true
			}
		}
	}
}
