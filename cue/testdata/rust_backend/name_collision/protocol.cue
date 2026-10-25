package rustcollision

import flow "github.com/jcfangc/cue-flow:cueflow"

#Ping: {
	value: string
}

protocol: flow.#Protocol & {
	messages: {
		Ping: #Ping
	}
	initial: "Ready"
	states: {
		Ready: {}
		ready: {}
	}
}
