package testdata

import flow "github.com/jcfangc/cue-flow:cueflow"

#Ping: {modelCopy: string}

protocol: flow.#Protocol & {
	messages: {Ping: #Ping}
	initial: "Ready"
	states: {
		Ready: {recv: {Ping: "Done"}}
		Done:  {}
	}
}
