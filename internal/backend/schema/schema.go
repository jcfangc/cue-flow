// 文件职责：将 CUE 消息约束解析为与目标语言无关的消息和字段模型。
// 各语言 backend 再把这个模型映射到自身的类型系统，不应在此加入语言专属限制。
package schema

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/big"
	"sort"
	"strconv"

	"cuelang.org/go/cue"
	"cuelang.org/go/encoding/jsonschema"
	"github.com/jcfangc/cue-flow/internal/compiler"
)

const (
	jsonTypeKeyword                 = "type"
	jsonPropertiesKeyword           = "properties"
	jsonRequiredKeyword             = "required"
	jsonAdditionalPropertiesKeyword = "additionalProperties"
	jsonTitleKeyword                = "title"
	jsonDescriptionKeyword          = "description"
	jsonPatternKeyword              = "pattern"
	jsonMinLengthKeyword            = "minLength"
	jsonMaxLengthKeyword            = "maxLength"
	jsonMinimumKeyword              = "minimum"
	jsonMaximumKeyword              = "maximum"
	jsonNotKeyword                  = "not"
	jsonAllOfKeyword                = "allOf"
)

type Kind string

const (
	String  Kind = "string"
	Integer Kind = "integer"
	Number  Kind = "number"
	Boolean Kind = "boolean"
	Object  Kind = "object"
)

type Message struct {
	ID     string
	Fields []Field
}

type Field struct {
	Name        string
	Kind        Kind
	Required    bool
	RejectEmpty bool
	Pattern     string
	MinLength   *int64
	MaxLength   *int64
	Minimum     *string
	Maximum     *string
	Fields      []Field
}

type jsonNotConstraint struct {
	Const json.RawMessage `json:"const"`
}

func LowerMessage(ctx *cue.Context, message compiler.Message) (Message, error) {
	expr, err := jsonschema.Generate(message.Constraint, nil)
	if err != nil {
		return Message{}, fmt.Errorf("cannot convert CUE constraint to JSON Schema: %w", err)
	}
	schemaValue := ctx.BuildExpr(expr)
	data, err := schemaValue.MarshalJSON()
	if err != nil {
		return Message{}, fmt.Errorf("cannot encode generated JSON Schema: %w", err)
	}
	definition, err := referencedDefinition(data)
	if err != nil {
		return Message{}, err
	}
	rootSchema, err := flattenSchema(definition.Root)
	if err != nil {
		return Message{}, err
	}
	var object struct {
		Type                 string                     `json:"type"`
		Properties           map[string]json.RawMessage `json:"properties"`
		Required             []string                   `json:"required"`
		AdditionalProperties *bool                      `json:"additionalProperties"`
	}
	if err := json.Unmarshal(rootSchema, &object); err != nil {
		return Message{}, err
	}
	if Kind(object.Type) != Object {
		return Message{}, fmt.Errorf("only CUE object message constraints are supported")
	}
	if object.AdditionalProperties != nil && *object.AdditionalProperties {
		return Message{}, fmt.Errorf("open message objects are not supported yet")
	}
	if err := rejectUnsupportedKeywords(rootSchema, map[string]struct{}{
		jsonTypeKeyword: {}, jsonPropertiesKeyword: {}, jsonRequiredKeyword: {},
		jsonAdditionalPropertiesKeyword: {}, jsonTitleKeyword: {}, jsonDescriptionKeyword: {},
	}, "object constraint"); err != nil {
		return Message{}, err
	}
	resolving := map[string]bool{definition.RootName: true}
	return lowerMessageFields(message.ID, object.Properties, object.Required, definition.Definitions, resolving)
}

func lowerMessageFields(
	id string,
	properties map[string]json.RawMessage,
	requiredNames []string,
	definitions map[string]json.RawMessage,
	resolving map[string]bool,
) (Message, error) {
	result := Message{ID: id}
	required := make(map[string]bool, len(requiredNames))
	for _, name := range requiredNames {
		required[name] = true
	}
	names := make([]string, 0, len(properties))
	for name := range properties {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		propertySchema, err := flattenSchema(properties[name])
		if err != nil {
			return Message{}, fmt.Errorf("field %q: %w", name, err)
		}
		field, err := lowerField(name, propertySchema, required[name], definitions, resolving)
		if err != nil {
			return Message{}, err
		}
		result.Fields = append(result.Fields, field)
	}
	return result, nil
}

func lowerField(
	name string,
	rawSchema json.RawMessage,
	required bool,
	definitions map[string]json.RawMessage,
	resolving map[string]bool,
) (Field, error) {
	reference, err := resolveReference(rawSchema, definitions)
	if err != nil {
		return Field{}, err
	}
	if reference.Name != "" && resolving[reference.Name] {
		return Field{}, fmt.Errorf("recursive CUE definition %q is not supported yet", reference.Name)
	}
	if reference.Name != "" {
		resolving[reference.Name] = true
		defer delete(resolving, reference.Name)
	}
	resolved, err := flattenSchema(reference.Schema)
	if err != nil {
		return Field{}, err
	}
	rawSchema = resolved
	var schema struct {
		Type                 string                     `json:"type"`
		Properties           map[string]json.RawMessage `json:"properties"`
		Required             []string                   `json:"required"`
		AdditionalProperties *bool                      `json:"additionalProperties"`
		Pattern              string                     `json:"pattern"`
		MinLength            *int64                     `json:"minLength"`
		MaxLength            *int64                     `json:"maxLength"`
		Minimum              *json.Number               `json:"minimum"`
		Maximum              *json.Number               `json:"maximum"`
		Not                  *jsonNotConstraint         `json:"not"`
	}
	if err := json.Unmarshal(rawSchema, &schema); err != nil {
		return Field{}, err
	}
	if err := rejectUnsupportedKeywords(rawSchema, map[string]struct{}{
		jsonTypeKeyword: {}, jsonPatternKeyword: {}, jsonMinLengthKeyword: {}, jsonMaxLengthKeyword: {},
		jsonMinimumKeyword: {}, jsonMaximumKeyword: {}, jsonNotKeyword: {}, jsonTitleKeyword: {}, jsonDescriptionKeyword: {},
		jsonPropertiesKeyword: {}, jsonRequiredKeyword: {}, jsonAdditionalPropertiesKeyword: {},
	}, fmt.Sprintf("field %q constraint", name)); err != nil {
		return Field{}, err
	}
	field := Field{
		Name: name, Kind: Kind(schema.Type), Required: required,
		Pattern: schema.Pattern, MinLength: schema.MinLength, MaxLength: schema.MaxLength,
	}
	if schema.Minimum != nil {
		minimum := schema.Minimum.String()
		field.Minimum = &minimum
	}
	if schema.Maximum != nil {
		maximum := schema.Maximum.String()
		field.Maximum = &maximum
	}
	if err := validateFieldConstraint(&field, schema.Minimum, schema.Maximum, schema.Not); err != nil {
		return Field{}, err
	}
	if field.Kind == Object {
		if schema.AdditionalProperties != nil && *schema.AdditionalProperties {
			return Field{}, fmt.Errorf("nested object field %q is open and is not supported yet", name)
		}
		nested, err := lowerMessageFields(name, schema.Properties, schema.Required, definitions, resolving)
		if err != nil {
			return Field{}, err
		}
		field.Fields = nested.Fields
	}
	return field, nil
}

func validateFieldConstraint(field *Field, minimum, maximum *json.Number, not *jsonNotConstraint) error {
	switch field.Kind {
	case String:
		if minimum != nil || maximum != nil {
			return fmt.Errorf("string field %q has numeric bounds that cannot be applied", field.Name)
		}
	case Integer, Number:
		if field.Pattern != "" || field.MinLength != nil || field.MaxLength != nil || not != nil {
			return fmt.Errorf("numeric field %q has a string-only constraint", field.Name)
		}
	case Boolean:
		if field.Pattern != "" || field.MinLength != nil || field.MaxLength != nil || minimum != nil || maximum != nil || not != nil {
			return fmt.Errorf("boolean field %q has unsupported value constraints", field.Name)
		}
	case Object:
		if field.Pattern != "" || field.MinLength != nil || field.MaxLength != nil || minimum != nil || maximum != nil || not != nil {
			return fmt.Errorf("object field %q has unsupported scalar constraints", field.Name)
		}
	default:
		return fmt.Errorf("field %q has unsupported JSON Schema type %q", field.Name, field.Kind)
	}
	if not != nil {
		if field.Kind == String && isEmptyStringConstant(not.Const) {
			field.RejectEmpty = true
		} else {
			return fmt.Errorf("field %q uses an unsupported not constraint", field.Name)
		}
	}
	return nil
}

func isEmptyStringConstant(value json.RawMessage) bool {
	trimmed := bytes.TrimSpace(value)
	if len(trimmed) < 2 || trimmed[0] != '"' {
		return false
	}
	var stringValue string
	return json.Unmarshal(trimmed, &stringValue) == nil && stringValue == ""
}

func rejectUnsupportedKeywords(raw json.RawMessage, allowed map[string]struct{}, description string) error {
	var keywords map[string]json.RawMessage
	if err := json.Unmarshal(raw, &keywords); err != nil {
		return err
	}
	for keyword := range keywords {
		if _, ok := allowed[keyword]; !ok {
			return fmt.Errorf("%s %q is not supported yet", description, keyword)
		}
	}
	return nil
}

func flattenSchema(raw json.RawMessage) (json.RawMessage, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return nil, err
	}
	allOf, hasAllOf := fields[jsonAllOfKeyword]
	delete(fields, jsonAllOfKeyword)
	if hasAllOf {
		if err := mergeAllOf(fields, allOf); err != nil {
			return nil, err
		}
	}
	return json.Marshal(fields)
}

func mergeAllOf(fields map[string]json.RawMessage, allOf json.RawMessage) error {
	var parts []json.RawMessage
	if err := json.Unmarshal(allOf, &parts); err != nil {
		return fmt.Errorf("allOf must be an array: %w", err)
	}
	for _, part := range parts {
		flattened, err := flattenSchema(part)
		if err != nil {
			return err
		}
		if err := mergeSchemaPart(fields, flattened); err != nil {
			return err
		}
	}
	return nil
}

func mergeSchemaPart(fields map[string]json.RawMessage, rawPart json.RawMessage) error {
	var partFields map[string]json.RawMessage
	if err := json.Unmarshal(rawPart, &partFields); err != nil {
		return err
	}
	for key, value := range partFields {
		current, exists := fields[key]
		if !exists || bytes.Equal(current, value) {
			fields[key] = value
			continue
		}
		merged, err := mergeConstraint(key, current, value)
		if err != nil {
			return err
		}
		fields[key] = merged
	}
	return nil
}

func mergeConstraint(key string, current, next json.RawMessage) (json.RawMessage, error) {
	switch key {
	case jsonTypeKeyword:
		return mergeTypes(current, next)
	case jsonMinimumKeyword, jsonMaximumKeyword:
		return mergeBounds(key, current, next)
	case jsonMinLengthKeyword, jsonMaxLengthKeyword:
		return mergeLengths(key, current, next)
	default:
		return nil, fmt.Errorf("multiple incompatible JSON Schema %q constraints are unsupported", key)
	}
}

func mergeTypes(current, next json.RawMessage) (json.RawMessage, error) {
	var left, right string
	_ = json.Unmarshal(current, &left)
	_ = json.Unmarshal(next, &right)
	if Kind(left) == Number && Kind(right) == Integer || Kind(left) == Integer && Kind(right) == Number {
		return json.RawMessage(strconv.Quote(string(Integer))), nil
	}
	if left == right {
		return current, nil
	}
	return nil, fmt.Errorf("incompatible JSON Schema types %q and %q", left, right)
}

func mergeBounds(key string, current, next json.RawMessage) (json.RawMessage, error) {
	var left, right big.Rat
	if _, ok := left.SetString(string(current)); !ok {
		return nil, fmt.Errorf("invalid numeric JSON Schema bound %s", current)
	}
	if _, ok := right.SetString(string(next)); !ok {
		return nil, fmt.Errorf("invalid numeric JSON Schema bound %s", next)
	}
	comparison := left.Cmp(&right)
	if key == jsonMinimumKeyword && comparison >= 0 || key == jsonMaximumKeyword && comparison <= 0 {
		return current, nil
	}
	return next, nil
}

func mergeLengths(key string, current, next json.RawMessage) (json.RawMessage, error) {
	left, leftErr := strconv.ParseInt(string(current), 10, 64)
	right, rightErr := strconv.ParseInt(string(next), 10, 64)
	if leftErr != nil || rightErr != nil {
		return nil, fmt.Errorf("invalid JSON Schema length constraint")
	}
	if key == jsonMinLengthKeyword && left >= right || key == jsonMaxLengthKeyword && left <= right {
		return current, nil
	}
	return next, nil
}
