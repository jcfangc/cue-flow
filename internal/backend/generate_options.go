// Package backend defines the language-independent choices for generated APIs.
package backend

import (
	"fmt"

	"github.com/jcfangc/cue-flow/internal/compiler"
)

type Endpoint string
type Runtime string
type Transport string
type Codec string

const (
	ClientEndpoint Endpoint = "client"
	ServerEndpoint Endpoint = "server"
	BothEndpoints  Endpoint = "both"

	TokioRuntime   Runtime = "tokio"
	AsyncioRuntime Runtime = "asyncio"

	WebSocketTransport Transport = "websocket"
	JSONCodec          Codec     = "json"
	CBORCodec          Codec     = "cbor"
)

// GenerateOptions selects the concrete runtime binding for generated APIs.
// Empty runtime, transport, and codec values retain the transport-neutral API.
type GenerateOptions struct {
	Endpoint  Endpoint
	Runtime   Runtime
	Transport Transport
	Codec     Codec
}

func (options GenerateOptions) HasBinding() bool {
	return options.Runtime != "" || options.Transport != "" || options.Codec != ""
}

func (options GenerateOptions) Validate() error {
	if err := options.validateEndpoint(); err != nil {
		return err
	}
	if !options.HasBinding() {
		return nil
	}
	if options.Runtime == "" || options.Transport == "" || options.Codec == "" {
		return fmt.Errorf("--runtime, --transport, and --codec must be selected together")
	}
	if options.Runtime != TokioRuntime && options.Runtime != AsyncioRuntime {
		return fmt.Errorf("unsupported runtime %q", options.Runtime)
	}
	if options.Transport != WebSocketTransport {
		return fmt.Errorf("unsupported transport %q", options.Transport)
	}
	if options.Codec != JSONCodec && options.Codec != CBORCodec {
		return fmt.Errorf("unsupported codec %q", options.Codec)
	}
	return nil
}

func (options GenerateOptions) ValidateRuntime(expected Runtime) error {
	if !options.HasBinding() || options.Runtime == expected {
		return nil
	}
	return fmt.Errorf(
		"runtime %q is not supported by this language backend; use %q",
		options.Runtime,
		expected,
	)
}

func (options GenerateOptions) ValidateProtocol(protocol *compiler.Protocol) error {
	for _, state := range protocol.States {
		if options.generatesServer() && len(state.Receives) > 1 {
			return fmt.Errorf(
				"state %q has multiple server receive transitions, ambiguous for endpoint %q",
				state.ID,
				options.Endpoint,
			)
		}
		if options.generatesClient() && len(state.Sends) > 1 {
			return fmt.Errorf(
				"state %q has multiple server send transitions, ambiguous for endpoint %q",
				state.ID,
				options.Endpoint,
			)
		}
	}
	return nil
}

func (options GenerateOptions) validateEndpoint() error {
	if options.Endpoint == "" {
		return fmt.Errorf("endpoint must be client, server, or both")
	}
	if options.Endpoint != ClientEndpoint &&
		options.Endpoint != ServerEndpoint &&
		options.Endpoint != BothEndpoints {
		return fmt.Errorf("unsupported endpoint %q", options.Endpoint)
	}
	return nil
}

func (options GenerateOptions) generatesServer() bool {
	return options.Endpoint == ServerEndpoint || options.Endpoint == BothEndpoints
}

func (options GenerateOptions) generatesClient() bool {
	return options.Endpoint == ClientEndpoint || options.Endpoint == BothEndpoints
}
