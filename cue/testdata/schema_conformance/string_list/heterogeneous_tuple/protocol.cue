package heterogeneous_tuple

import flow "github.com/jcfangc/cue-flow:cueflow"

#Query: {values: [string, int]}

protocol: flow.#Protocol & {
	messages: {Query: #Query}
	initial:  "Ready"
	states:   {Ready: {recv: {Query: "Done"}}, Done: {}}
}
