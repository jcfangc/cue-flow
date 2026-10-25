package examples

import flow "github.com/jcfangc/cue-flow:cueflow"

#Query: {
	id:       string & !=""
	sequence: string & =~"^[ACGT]+$"
	topK:     int & >=1 & <=100
	note?:    string
	"gen"?:   string
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
			recv: {
				Query: "Waiting"
			}
		}
		Waiting: {
			send: {
				Result: "Ready"
			}
		}
	}
}

sample: {
	query: protocol.messages.Query & {
		id:       "q1"
		sequence: "ACGT"
		topK:     5
	}
	result: protocol.messages.Result & {
		id:     "q1"
		result: "matched"
	}
}
