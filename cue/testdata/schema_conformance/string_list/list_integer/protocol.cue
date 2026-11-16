package list_integer

import flow "github.com/jcfangc/cue-flow:cueflow"

#Query: {values: [...(int & >=1 & <=10)]}

protocol: flow.#Protocol & {
	messages: {Query: #Query}
	initial:  "Ready"
	states:   {Ready: {recv: {Query: "Done"}}, Done: {}}
}
