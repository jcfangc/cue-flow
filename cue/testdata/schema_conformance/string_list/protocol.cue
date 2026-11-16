package string_list

import flow "github.com/jcfangc/cue-flow:cueflow"

#Query: {
	tags:  [...(string & !="" & =~"^[a-z]+$")]
	notes?: [...string]
}

protocol: flow.#Protocol & {
	messages: {Query: #Query}
	initial:  "Ready"
	states: {
		Ready: {recv: {Query: "Done"}}
		Done:  {}
	}
}
