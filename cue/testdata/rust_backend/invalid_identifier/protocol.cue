package testdata

import flow "github.com/jcfangc/cue-flow:cueflow"

#Ping: {payload: string}

protocol: flow.#Protocol & {
	messages: {Ping: #Ping}
	initial: "_"
	states: {"_": {}}
}
