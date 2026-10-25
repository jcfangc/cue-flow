// 文件职责：把协议中的消息、状态和字段名称映射成安全且无冲突的 Python 标识符。
// 同时把共享 schema 字段关联到生成的 Python 类名和状态方法名。
package python

import (
	"fmt"
	"strings"

	"cuelang.org/go/cue/cuecontext"
	"github.com/jcfangc/cue-flow/internal/backend/schema"
	"github.com/jcfangc/cue-flow/internal/compiler"
)

type Protocol = compiler.Protocol
type State = compiler.State
type Transition = compiler.Transition
type Message = compiler.Message

type pythonNames struct {
	messages       []schema.Message
	messageClasses map[string]string
	stateClasses   map[string]map[string]string
	fieldNames     map[string]map[string]string
	serverSend     map[string]map[string]string
	serverReceive  map[string]map[string]string
	clientSend     map[string]map[string]string
	clientReceive  map[string]map[string]string
}

func lowerPythonNames(protocol *Protocol) (*pythonNames, error) {
	names := newPythonNames(protocol)
	usedTypes := pythonReservedTypes()
	context := cuecontext.New()
	for _, message := range protocol.Messages {
		lowered, err := schema.LowerMessage(context, message)
		if err != nil {
			return nil, fmt.Errorf("message %q: %w", message.ID, err)
		}
		className := pascalCase(message.ID)
		if !isPythonIdentifier(className) {
			return nil, fmt.Errorf("message ID %q maps to invalid Python class name %q", message.ID, className)
		}
		if err := registerName(usedTypes, className, message.ID, "message type"); err != nil {
			return nil, err
		}
		names.messageClasses[message.ID] = className
		names.messages = append(names.messages, lowered)
		if err := lowerPythonFields(names, lowered); err != nil {
			return nil, err
		}
	}
	if err := lowerStateClasses(names, protocol, usedTypes); err != nil {
		return nil, err
	}
	return names, nil
}

func newPythonNames(protocol *Protocol) *pythonNames {
	return &pythonNames{
		messageClasses: make(map[string]string, len(protocol.Messages)),
		stateClasses:   map[string]map[string]string{"server": {}, "client": {}},
		fieldNames:     make(map[string]map[string]string, len(protocol.Messages)),
		serverSend:     make(map[string]map[string]string, len(protocol.States)),
		serverReceive:  make(map[string]map[string]string, len(protocol.States)),
		clientSend:     make(map[string]map[string]string, len(protocol.States)),
		clientReceive:  make(map[string]map[string]string, len(protocol.States)),
	}
}

func pythonReservedTypes() map[string]string {
	return map[string]string{
		"BaseModel": "Pydantic base", "Closed": "generated outcome", "ConfigDict": "Pydantic config",
		"dataclass": "imported helper", "Exception": "built-in exception", "Field": "Pydantic field",
		"Generic": "typing helper", "Inbound": "generated type alias", "InboundClose": "generated event",
		"InboundMessage": "generated event", "MessageT": "generated type variable",
		"MessageValidationFailure": "generated error", "PydanticValidationError": "Pydantic error",
		"Protocol": "typing helper", "ProtocolError": "generated error", "Received": "generated outcome",
		"StateT": "generated type variable", "StrictBool": "Pydantic scalar", "StrictInt": "Pydantic scalar",
		"StrictStr": "Pydantic scalar", "Transport": "generated protocol", "TransportFailure": "generated error",
		"TypeVar": "typing helper", "UnexpectedMessage": "generated error", "ValueError": "built-in exception",
		"field_validator": "Pydantic validator",
	}
}

func lowerPythonFields(names *pythonNames, message schema.Message) error {
	names.fieldNames[message.ID] = make(map[string]string, len(message.Fields))
	used := pydanticFieldNames()
	for _, field := range message.Fields {
		fieldName := snakeCase(field.Name)
		if pythonKeyword(fieldName) || strings.HasPrefix(fieldName, "_") {
			fieldName = "cue_" + strings.TrimLeft(fieldName, "_")
		}
		if _, reserved := used[fieldName]; reserved {
			fieldName = "cue_" + fieldName
		}
		if !isPythonIdentifier(fieldName) {
			return fmt.Errorf("message %q field %q cannot be mapped to a valid Python identifier", message.ID, field.Name)
		}
		if err := registerName(used, fieldName, field.Name, "field"); err != nil {
			return fmt.Errorf("message %q: %w", message.ID, err)
		}
		names.fieldNames[message.ID][field.Name] = fieldName
	}
	return nil
}

func pydanticFieldNames() map[string]string {
	return map[string]string{
		"model_computed_fields": "Pydantic metadata", "model_config": "Pydantic config",
		"model_construct": "Pydantic method", "model_copy": "Pydantic method",
		"model_dump": "Pydantic method", "model_dump_json": "Pydantic method",
		"model_extra": "Pydantic metadata", "model_fields": "Pydantic metadata",
		"model_fields_set": "Pydantic metadata", "model_json_schema": "Pydantic method",
		"model_parametrized_name": "Pydantic method", "model_post_init": "Pydantic method",
		"model_rebuild": "Pydantic method", "model_validate": "Pydantic method",
		"model_validate_json": "Pydantic method", "model_validate_strings": "Pydantic method",
		"construct": "Pydantic compatibility method", "copy": "Pydantic compatibility method",
		"dict": "Pydantic compatibility method", "json": "Pydantic compatibility method",
		"parse_file": "Pydantic compatibility method", "parse_obj": "Pydantic compatibility method",
		"parse_raw": "Pydantic compatibility method", "schema": "Pydantic compatibility method",
		"schema_json": "Pydantic compatibility method", "update_forward_refs": "Pydantic compatibility method",
		"validate": "Pydantic compatibility method",
	}
}

func lowerStateClasses(names *pythonNames, protocol *Protocol, usedTypes map[string]string) error {
	for _, state := range protocol.States {
		for _, endpoint := range []string{"server", "client"} {
			className := pascalCase(endpoint + "_" + state.ID)
			if !isPythonIdentifier(className) {
				return fmt.Errorf("state ID %q maps to invalid Python class name %q", state.ID, className)
			}
			if err := registerName(usedTypes, className, endpoint+" state "+state.ID, "generated type"); err != nil {
				return err
			}
			names.stateClasses[endpoint][state.ID] = className
		}
		if err := lowerStateMethods(names, state); err != nil {
			return err
		}
	}
	return nil
}

func lowerStateMethods(names *pythonNames, state State) error {
	if len(state.Receives) > 1 {
		return fmt.Errorf("state %q has multiple receive transitions, unsupported by the Python backend", state.ID)
	}
	server, client := initialMethods(), initialMethods()
	names.serverSend[state.ID] = make(map[string]string, len(state.Sends))
	names.clientReceive[state.ID] = make(map[string]string, len(state.Sends))
	for _, transition := range state.Sends {
		if err := registerTransitionMethods(server, client, transition, "send", "recv", names.serverSend[state.ID], names.clientReceive[state.ID]); err != nil {
			return fmt.Errorf("state %q: %w", state.ID, err)
		}
	}
	names.serverReceive[state.ID] = make(map[string]string, len(state.Receives))
	names.clientSend[state.ID] = make(map[string]string, len(state.Receives))
	for _, transition := range state.Receives {
		if err := registerTransitionMethods(server, client, transition, "recv", "send", names.serverReceive[state.ID], names.clientSend[state.ID]); err != nil {
			return fmt.Errorf("state %q: %w", state.ID, err)
		}
	}
	return nil
}

func registerTransitionMethods(server, client map[string]string, transition Transition, serverDirection, clientDirection string, serverNames, clientNames map[string]string) error {
	serverName := snakeCase(serverDirection + "_" + transition.MessageID)
	clientName := snakeCase(clientDirection + "_" + transition.MessageID)
	if err := registerName(server, serverName, transition.MessageID, "server method"); err != nil {
		return err
	}
	if err := registerName(client, clientName, transition.MessageID, "client method"); err != nil {
		return err
	}
	serverNames[transition.MessageID] = serverName
	clientNames[transition.MessageID] = clientName
	return nil
}

func initialMethods() map[string]string {
	return map[string]string{"close": "implicit Close", "recv_close": "implicit Close"}
}

func registerName(names map[string]string, targetName, sourceName, role string) error {
	if previous, exists := names[targetName]; exists {
		return fmt.Errorf("%s names %q and %q map to duplicate Python identifier %q", role, previous, sourceName, targetName)
	}
	names[targetName] = sourceName
	return nil
}

func pascalCase(input string) string {
	parts := splitWords(input)
	var builder strings.Builder
	for _, part := range parts {
		runes := []rune(strings.ToLower(part))
		if len(runes) == 0 {
			continue
		}
		runes[0] = []rune(strings.ToUpper(string(runes[0])))[0]
		builder.WriteString(string(runes))
	}
	if builder.Len() == 0 {
		return "Generated"
	}
	name := builder.String()
	if name[0] >= '0' && name[0] <= '9' {
		return "N" + name
	}
	return name
}

func snakeCase(input string) string {
	parts := splitWords(input)
	return strings.ToLower(strings.Join(parts, "_"))
}

func splitWords(input string) []string {
	var parts []string
	var current strings.Builder
	var previous rune
	for _, char := range input {
		if char >= 'A' && char <= 'Z' && current.Len() > 0 && (previous >= 'a' && previous <= 'z' || previous >= '0' && previous <= '9') {
			parts = append(parts, current.String())
			current.Reset()
		}
		if isASCIIAlphaNumeric(char) {
			current.WriteRune(char)
			previous = char
			continue
		}
		if current.Len() > 0 {
			parts = append(parts, current.String())
			current.Reset()
		}
		previous = char
	}
	if current.Len() > 0 {
		parts = append(parts, current.String())
	}
	return parts
}

func isPythonIdentifier(name string) bool {
	if name == "" || name[0] >= '0' && name[0] <= '9' {
		return false
	}
	for _, char := range name {
		if char != '_' && !isASCIIAlphaNumeric(char) {
			return false
		}
	}
	return !pythonKeyword(name)
}

func isASCIIAlphaNumeric(char rune) bool {
	return char >= 'A' && char <= 'Z' || char >= 'a' && char <= 'z' || char >= '0' && char <= '9'
}

func pythonKeyword(name string) bool {
	switch name {
	case "False", "None", "True", "and", "as", "assert", "async", "await", "break", "case", "class", "continue", "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "match", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield":
		return true
	default:
		return false
	}
}
