package testdata

import flow "github.com/jcfangc/cue-flow:cueflow"

#Ping: {payload: string}
#Pong: {payload: string}

protocol: flow.#Protocol & {
	messages: {
		Ping: #Ping
		Pong: #Pong
	}
	initial: "Ready"
	states: {
		Ready: {
			recv: {
				Ping: "AfterPing"
				Pong: "AfterPong"
			}
		}
		AfterPing: {}
		AfterPong: {}
	}
}
