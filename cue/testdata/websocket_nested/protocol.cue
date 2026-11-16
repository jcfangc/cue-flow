package websocket_nested

import flow "github.com/jcfangc/cue-flow:cueflow"

#QueryFilterRange: {
	topK:   int & >=1 & <=100
	active: bool
}

#QueryFilter: {
	sequence: string & =~"^[ACGT]+$"
	range:    #QueryFilterRange
	note?:    string
}

#QueryDetails: {
	label: string & !=""
}

#Query: {
	id:      string & !=""
	filter:  #QueryFilter
	details?: #QueryDetails
}

#ResultPayload: {
	summary: string & !=""
	matches: int & >=1 & <=100
}

#Result: {
	id:      string & !=""
	payload: #ResultPayload
}

protocol: flow.#Protocol & {
	messages: {
		Query:  #Query
		Result: #Result
	}
	initial: "Ready"
	states: {
		Ready:   {recv: {Query: "Waiting"}}
		Waiting: {send: {Result: "Ready"}}
	}
}
