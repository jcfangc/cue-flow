package cueflow

#StateID:   string
#MessageID: string

#State: close({
	// send and recv are defined from the server's point of view.
	send?: [#MessageID]: #StateID
	recv?: [#MessageID]: #StateID
})

#Protocol: {
	// messages maps each protocol-level message ID to its CUE value constraint.
	messages!: [#MessageID]: _
	initial!: #StateID
	states!: [#StateID]: #State
}
