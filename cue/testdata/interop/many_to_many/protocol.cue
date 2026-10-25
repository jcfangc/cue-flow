package interop

import flow "github.com/jcfangc/cue-flow:cueflow"

#Query: {
	id: string & !=""
}

#Finish: {
	id: string & !=""
}

#Result: {
	id:     string & !=""
	result: string
}

protocol: flow.#Protocol & {
	messages: {
		Query:  #Query
		Finish: #Finish
		Result: #Result
	}
	initial: "Ready"
	states: {
		Ready: {
			recv: {Query: "SecondQuery"}
		}
		SecondQuery: {
			recv: {Query: "ThirdQuery"}
		}
		ThirdQuery: {
			recv: {Query: "AwaitFinish"}
		}
		AwaitFinish: {
			recv: {Finish: "Streaming"}
		}
		Streaming: {
			send: {Result: "Streaming"}
		}
	}
}
