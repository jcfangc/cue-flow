package testdata

import flow "github.com/jcfangc/cue-flow:cueflow"

#Finished: {
	status: string
}

protocol: flow.#Protocol & {
	messages: {
		Finished: #Finished
	}
	initial: "Ready"
	states: {
		Ready: {
			send: {
				Finished: "End"
			}
		}
		End: {}
	}
}
