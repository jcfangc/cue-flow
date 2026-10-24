package cueflow

#StateID:   string
#MessageID: string

#State: {
	send?: [#MessageID]: #StateID
	recv?: [#MessageID]: #StateID
	// Close is a payload-free logical session event. When enabled, either
	// endpoint may send it or receive it from its peer (dual(Close) = Close).
	// Sending or receiving Close moves the session to an implicit terminal
	// state with no further business communication. It needs no acknowledgement
	// and does not define the lifetime of the underlying transport connection.
	close?: true
}

#Protocol: {
	// messages maps each protocol-level message ID to its CUE value constraint.
	messages!: [#MessageID]: _
	initial!: #StateID
	states!: [#StateID]: #State
	// CueFlow semantic validation must check that initial and transition target
	// state IDs exist, and that send/recv message IDs exist in messages.
}
