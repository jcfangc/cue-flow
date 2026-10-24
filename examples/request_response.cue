package examples

import flow "github.com/jcfangc/cue-flow:cueflow"

#Query: {
	id:       string & !=""
	sequence: string & =~"^[ACGT]+$"
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
			send: {
				Query: "Waiting"
			}
			close: true
		}
		Waiting: {
			recv: {
				Result: "Ready"
			}
		}
	}
}

sample: {
	query: protocol.messages.Query & {
		id:       "q1"
		sequence: "ACGT"
	}
	result: protocol.messages.Result & {
		id:     "q1"
		result: "matched"
	}
}
