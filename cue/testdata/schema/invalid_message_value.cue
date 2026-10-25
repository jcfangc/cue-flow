package testdata

import flow "github.com/jcfangc/cue-flow:cueflow"

#Query: {
	id:       string & !=""
	sequence: string & =~"^[ACGT]+$"
	topK:     int & >=1 & <=100
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
		}
		Waiting: {
			recv: {
				Result: "Ready"
			}
		}
	}
}

sample: protocol.messages.Query & {
	id:       "q1"
	sequence: "ACNT"
	topK:     5
}
