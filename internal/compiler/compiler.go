package compiler

import (
	"fmt"
	"sort"

	"cuelang.org/go/cue"
	"cuelang.org/go/cue/cuecontext"
	"cuelang.org/go/cue/load"
)

const (
	protocolFieldName = "protocol"
	initialFieldName  = "initial"
	messagesFieldName = "messages"
	statesFieldName   = "states"
)

type direction string

const (
	serverSend direction = "send"
	serverRecv direction = "recv"
)

type Protocol struct {
	Initial   string
	States    []State
	Messages  []Message
	byState   map[string]State
	byMessage map[string]Message
}

type State struct {
	ID       string
	Sends    []Transition
	Receives []Transition
	Terminal bool
}

type Transition struct {
	MessageID string
	Target    string
}

type Message struct {
	ID         string
	Constraint cue.Value
}

// Load evaluates a CUE package using CUE's Go API and reads its `protocol` value.
func Load(packageDir string) (*Protocol, error) {
	ctx := cuecontext.New()
	instances := load.Instances([]string{"."}, &load.Config{Dir: packageDir})
	if len(instances) != 1 {
		return nil, fmt.Errorf("expected one CUE package in %s, found %d", packageDir, len(instances))
	}
	if instances[0].Err != nil {
		return nil, instances[0].Err
	}
	root := ctx.BuildInstance(instances[0])
	if err := root.Err(); err != nil {
		return nil, err
	}
	protocolValue := root.LookupPath(cue.ParsePath(protocolFieldName))
	if !protocolValue.Exists() {
		return nil, fmt.Errorf("CUE package must define protocol")
	}
	if err := protocolValue.Validate(cue.Final()); err != nil {
		return nil, fmt.Errorf("invalid protocol value: %w", err)
	}

	protocol, err := parseProtocol(protocolValue)
	if err != nil {
		return nil, err
	}
	return protocol, nil
}

func parseProtocol(value cue.Value) (*Protocol, error) {
	initial, err := stringAt(value, initialFieldName)
	if err != nil {
		return nil, err
	}
	messageValues, err := fieldsAt(value, messagesFieldName)
	if err != nil {
		return nil, err
	}
	stateValues, err := fieldsAt(value, statesFieldName)
	if err != nil {
		return nil, err
	}
	if len(stateValues) == 0 {
		return nil, fmt.Errorf("protocol.states must contain at least one state")
	}
	if len(messageValues) == 0 {
		return nil, fmt.Errorf("protocol.messages must contain at least one message")
	}

	p := &Protocol{
		Initial:   initial,
		byState:   make(map[string]State, len(stateValues)),
		byMessage: make(map[string]Message, len(messageValues)),
	}
	for id, constraint := range messageValues {
		if id == "" {
			return nil, fmt.Errorf("protocol message IDs must not be empty")
		}
		message := Message{ID: id, Constraint: constraint}
		p.byMessage[id] = message
		p.Messages = append(p.Messages, message)
	}
	sort.Slice(p.Messages, func(i, j int) bool { return p.Messages[i].ID < p.Messages[j].ID })

	for id, stateValue := range stateValues {
		if id == "" {
			return nil, fmt.Errorf("protocol state IDs must not be empty")
		}
		state, err := parseState(id, stateValue)
		if err != nil {
			return nil, err
		}
		p.byState[id] = state
		p.States = append(p.States, state)
	}
	sort.Slice(p.States, func(i, j int) bool { return p.States[i].ID < p.States[j].ID })

	for i := range p.States {
		state := &p.States[i]
		state.Terminal = len(state.Sends) == 0 && len(state.Receives) == 0
	}
	return p, nil
}

func validateTransition(p *Protocol, state *State, transition *Transition) error {
	if _, ok := p.byState[transition.Target]; !ok {
		return fmt.Errorf("state %q transition for message %q targets undeclared state %q", state.ID, transition.MessageID, transition.Target)
	}
	if _, ok := p.byMessage[transition.MessageID]; !ok {
		return fmt.Errorf("state %q references unregistered message %q", state.ID, transition.MessageID)
	}
	return nil
}

func parseState(id string, value cue.Value) (State, error) {
	state := State{ID: id}
	for _, direction := range []struct {
		name direction
		dst  *[]Transition
	}{{serverSend, &state.Sends}, {serverRecv, &state.Receives}} {
		v := value.LookupPath(cue.ParsePath(string(direction.name)))
		if !v.Exists() {
			continue
		}
		fields, err := cueFields(v)
		if err != nil {
			return State{}, fmt.Errorf("state %q %s: %w", id, direction.name, err)
		}
		for messageID, targetValue := range fields {
			target, err := targetValue.String()
			if err != nil {
				return State{}, fmt.Errorf("state %q %s.%s must name a target state", id, direction.name, messageID)
			}
			*direction.dst = append(*direction.dst, Transition{
				MessageID: messageID,
				Target:    target,
			})
		}
		sort.Slice(*direction.dst, func(i, j int) bool { return (*direction.dst)[i].MessageID < (*direction.dst)[j].MessageID })
	}
	return state, nil
}

func fieldsAt(value cue.Value, field string) (map[string]cue.Value, error) {
	v := value.LookupPath(cue.ParsePath(field))
	if !v.Exists() {
		return nil, fmt.Errorf("protocol.%s is required", field)
	}
	return cueFields(v)
}

func cueFields(value cue.Value) (map[string]cue.Value, error) {
	iter, err := value.Fields()
	if err != nil {
		return nil, err
	}
	fields := map[string]cue.Value{}
	for iter.Next() {
		fields[iter.Selector().Unquoted()] = iter.Value()
	}
	return fields, nil
}

func stringAt(value cue.Value, field string) (string, error) {
	v := value.LookupPath(cue.ParsePath(field))
	if !v.Exists() {
		return "", fmt.Errorf("protocol.%s is required", field)
	}
	s, err := v.String()
	if err != nil {
		return "", fmt.Errorf("protocol.%s must be a string: %w", field, err)
	}
	return s, nil
}

func Check(p *Protocol) error {
	if p == nil {
		return fmt.Errorf("protocol is empty")
	}
	if _, ok := p.byState[p.Initial]; !ok {
		return fmt.Errorf("initial state %q is not declared in protocol.states", p.Initial)
	}
	for i := range p.States {
		state := &p.States[i]
		for j := range state.Sends {
			if err := validateTransition(p, state, &state.Sends[j]); err != nil {
				return err
			}
		}
		for j := range state.Receives {
			if err := validateTransition(p, state, &state.Receives[j]); err != nil {
				return err
			}
		}
	}
	return nil
}
