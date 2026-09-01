package cueflow

#StateID:   string
#MessageID: string

#State: {
	send?: [#MessageID]: #StateID
	recv?: [#MessageID]: #StateID
}

#Protocol: {
	initial: #StateID
	states: [#StateID]: #State
}
