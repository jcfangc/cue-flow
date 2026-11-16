package string_list

sample: protocol.messages.Query & {
	tags:  ["alpha", "beta"]
	notes: []
}

emptySample: protocol.messages.Query & {tags: []}
