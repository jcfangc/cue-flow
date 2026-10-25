package rust

import (
	"fmt"
	"strings"

	"cuelang.org/go/cue/cuecontext"
	"github.com/jcfangc/cue-flow/internal/compiler"
)

type Protocol = compiler.Protocol
type State = compiler.State
type Transition = compiler.Transition
type Message = compiler.Message

type rustNames struct {
	messages          []rustMessage
	messageTypes      map[string]string
	stateTypes        map[string]string
	fieldNames        map[string]map[string]string
	fieldTypes        map[string]map[string]string
	serverSendMethods map[string]map[string]string
	serverRecvMethods map[string]map[string]string
	clientSendMethods map[string]map[string]string
	clientRecvMethods map[string]map[string]string
}

func lowerRustNames(p *Protocol) (*rustNames, error) {
	names := &rustNames{
		messageTypes:      make(map[string]string, len(p.Messages)),
		stateTypes:        make(map[string]string, len(p.States)),
		fieldNames:        make(map[string]map[string]string, len(p.Messages)),
		fieldTypes:        make(map[string]map[string]string, len(p.Messages)),
		serverSendMethods: make(map[string]map[string]string, len(p.States)),
		serverRecvMethods: make(map[string]map[string]string, len(p.States)),
		clientSendMethods: make(map[string]map[string]string, len(p.States)),
		clientRecvMethods: make(map[string]map[string]string, len(p.States)),
	}
	messageNames := map[string]string{}
	ctx := cuecontext.New()
	for _, message := range p.Messages {
		spec, err := parseRustMessage(ctx, message)
		if err != nil {
			return nil, fmt.Errorf("message %q: %w", message.ID, err)
		}
		typeName := pascalCase(message.ID)
		if err := registerRustName(messageNames, typeName, message.ID, "message type"); err != nil {
			return nil, err
		}
		names.messageTypes[message.ID] = typeName
		spec.TypeName = typeName
		if err := lowerRustFields(names, &spec); err != nil {
			return nil, err
		}
		names.messages = append(names.messages, spec)
	}
	stateNames := map[string]string{}
	reservedStateNames := map[string]struct{}{
		"ServerSession": {}, "ClientSession": {}, "Transport": {}, "ProtocolError": {},
		"Inbound": {}, "ReceiveOutcome": {}, "PhantomData": {},
	}
	for _, state := range p.States {
		stateName := pascalCase(state.ID)
		if _, reserved := reservedStateNames[stateName]; reserved {
			return nil, fmt.Errorf("state ID %q maps to reserved generated Rust name %q", state.ID, stateName)
		}
		if err := registerRustName(stateNames, stateName, state.ID, "state marker"); err != nil {
			return nil, err
		}
		names.stateTypes[state.ID] = stateName
		if err := lowerRustMethods(names, state); err != nil {
			return nil, err
		}
	}
	return names, nil
}

func lowerRustFields(names *rustNames, message *rustMessage) error {
	fieldNames := make(map[string]string, len(message.Fields))
	names.fieldNames[message.ID] = make(map[string]string, len(message.Fields))
	names.fieldTypes[message.ID] = make(map[string]string, len(message.Fields))
	for i := range message.Fields {
		field := &message.Fields[i]
		fieldName := rustField(snakeCase(field.Name))
		if fieldName == "" {
			return fmt.Errorf("field %q cannot be mapped to a Rust identifier", field.Name)
		}
		if err := registerRustName(fieldNames, fieldName, field.Name, "field"); err != nil {
			return fmt.Errorf("message %q: %w", message.ID, err)
		}
		field.RustName = fieldName
		names.fieldNames[message.ID][field.Name] = fieldName
		names.fieldTypes[message.ID][field.Name] = field.RustType
	}
	return nil
}

func lowerRustMethods(names *rustNames, state State) error {
	serverMethods := map[string]string{"recv_close": "implicit Close"}
	clientMethods := map[string]string{"recv_close": "implicit Close"}
	names.serverSendMethods[state.ID] = make(map[string]string, len(state.Sends))
	names.clientRecvMethods[state.ID] = make(map[string]string, len(state.Sends))
	for _, transition := range state.Sends {
		serverMethod := snakeCase("send_" + transition.MessageID)
		if err := registerRustName(serverMethods, serverMethod, transition.MessageID, "method"); err != nil {
			return fmt.Errorf("state %q: %w", state.ID, err)
		}
		names.serverSendMethods[state.ID][transition.MessageID] = serverMethod
		clientMethod := snakeCase("recv_" + transition.MessageID)
		if err := registerRustName(clientMethods, clientMethod, transition.MessageID, "method"); err != nil {
			return fmt.Errorf("state %q client: %w", state.ID, err)
		}
		names.clientRecvMethods[state.ID][transition.MessageID] = clientMethod
	}
	names.serverRecvMethods[state.ID] = make(map[string]string, len(state.Receives))
	names.clientSendMethods[state.ID] = make(map[string]string, len(state.Receives))
	for _, transition := range state.Receives {
		serverMethod := snakeCase("recv_" + transition.MessageID)
		if err := registerRustName(serverMethods, serverMethod, transition.MessageID, "method"); err != nil {
			return fmt.Errorf("state %q: %w", state.ID, err)
		}
		names.serverRecvMethods[state.ID][transition.MessageID] = serverMethod
		clientMethod := snakeCase("send_" + transition.MessageID)
		if err := registerRustName(clientMethods, clientMethod, transition.MessageID, "method"); err != nil {
			return fmt.Errorf("state %q client: %w", state.ID, err)
		}
		names.clientSendMethods[state.ID][transition.MessageID] = clientMethod
	}
	return nil
}

func registerRustName(names map[string]string, rustName, sourceName, description string) error {
	if previous, exists := names[rustName]; exists {
		return fmt.Errorf("%s IDs %q and %q produce duplicate Rust name %q", description, previous, sourceName, rustName)
	}
	names[rustName] = sourceName
	return nil
}

func pascalCase(input string) string {
	if isRustIdent(input) {
		runes := []rune(input)
		if len(runes) > 0 && runes[0] >= 'a' && runes[0] <= 'z' {
			runes[0] -= 'a' - 'A'
		}
		name := string(runes)
		if isRustKeyword(name) {
			return "Cue" + name
		}
		return name
	}
	parts := splitWords(input)
	var b strings.Builder
	for _, part := range parts {
		runes := []rune(strings.ToLower(part))
		if len(runes) > 0 {
			runes[0] = []rune(strings.ToUpper(string(runes[0])))[0]
			b.WriteString(string(runes))
		}
	}
	if b.Len() == 0 {
		return "Generated"
	}
	if first := []rune(b.String())[0]; first >= '0' && first <= '9' {
		return "N" + b.String()
	}
	name := b.String()
	if isRustKeyword(name) {
		return "Cue" + name
	}
	return name
}

func snakeCase(input string) string {
	parts := splitWords(input)
	name := strings.ToLower(strings.Join(parts, "_"))
	if name != "" && name[0] >= '0' && name[0] <= '9' {
		return "n_" + name
	}
	return name
}

func isRustKeyword(name string) bool {
	switch name {
	case "Self", "self", "type", "match", "ref", "loop", "move", "mod", "use", "where", "async", "await", "dyn", "crate", "super", "fn", "struct", "enum", "trait", "impl", "const", "static", "let", "return", "break", "continue", "if", "else", "while", "for", "in", "as", "extern", "unsafe", "pub", "mut", "true", "false", "abstract", "become", "box", "do", "final", "macro", "override", "priv", "typeof", "unsized", "virtual", "yield", "gen":
		return true
	default:
		return false
	}
}

func splitWords(input string) []string {
	var words []string
	var current strings.Builder
	var previous rune
	for _, r := range input {
		if r >= 'A' && r <= 'Z' && current.Len() > 0 && (previous >= 'a' && previous <= 'z' || previous >= '0' && previous <= '9') {
			words = append(words, current.String())
			current.Reset()
		}
		if r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || r >= '0' && r <= '9' {
			current.WriteRune(r)
			previous = r
			continue
		}
		if current.Len() > 0 {
			words = append(words, current.String())
			current.Reset()
		}
		previous = r
	}
	if current.Len() > 0 {
		words = append(words, current.String())
	}
	return words
}

func isRustIdent(input string) bool {
	if input == "" {
		return false
	}
	for i, r := range input {
		if r == '_' || r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || i > 0 && r >= '0' && r <= '9' {
			continue
		}
		return false
	}
	return true
}

func rustField(name string) string {
	if isRustKeyword(name) {
		return "cue_" + name
	}
	return name
}
