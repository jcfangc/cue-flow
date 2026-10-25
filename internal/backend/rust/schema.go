package rust

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/big"
	"sort"
	"strconv"
	"strings"

	"cuelang.org/go/cue"
	"cuelang.org/go/encoding/jsonschema"
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

type jsonValueType string

const (
	jsonObjectType  jsonValueType = "object"
	jsonStringType  jsonValueType = "string"
	jsonIntegerType jsonValueType = "integer"
	jsonNumberType  jsonValueType = "number"
	jsonBooleanType jsonValueType = "boolean"
)

type rustMessage struct {
	ID       string
	TypeName string
	Fields   []rustMessageField
}

type rustMessageField struct {
	Name        string
	RustName    string
	RustType    string
	Required    bool
	RejectEmpty bool
	Pattern     string
	MinLength   *int64
	MaxLength   *int64
	MinInt      *int64
	MaxInt      *int64
}

type jsonNotConstraint struct {
	Const any `json:"const"`
}

func rustType(kind jsonValueType) (string, error) {
	switch kind {
	case jsonStringType:
		return "String", nil
	case jsonIntegerType:
		return "i64", nil
	case jsonBooleanType:
		return "bool", nil
	default:
		return "", fmt.Errorf("unsupported field kind %q", kind)
	}
}

func parseRustMessage(ctx *cue.Context, message Message) (rustMessage, error) {
	expr, err := jsonschema.Generate(message.Constraint, nil)
	if err != nil {
		return rustMessage{}, fmt.Errorf("cannot convert CUE constraint to JSON Schema: %w", err)
	}
	schemaValue := ctx.BuildExpr(expr)
	data, err := schemaValue.MarshalJSON()
	if err != nil {
		return rustMessage{}, fmt.Errorf("cannot encode generated JSON Schema: %w", err)
	}
	var envelope struct {
		Ref  string                     `json:"$ref"`
		Defs map[string]json.RawMessage `json:"$defs"`
	}
	if err := json.Unmarshal(data, &envelope); err != nil {
		return rustMessage{}, err
	}
	definitionName := strings.TrimPrefix(envelope.Ref, "#/$defs/")
	definition, ok := envelope.Defs[definitionName]
	if !ok || definitionName == envelope.Ref {
		return rustMessage{}, fmt.Errorf("unsupported generated JSON Schema reference %q", envelope.Ref)
	}
	definition, err = flattenSchema(definition)
	if err != nil {
		return rustMessage{}, err
	}
	var object struct {
		Type                 string                     `json:"type"`
		Properties           map[string]json.RawMessage `json:"properties"`
		Required             []string                   `json:"required"`
		AdditionalProperties *bool                      `json:"additionalProperties"`
	}
	if err := json.Unmarshal(definition, &object); err != nil {
		return rustMessage{}, err
	}
	if jsonValueType(object.Type) != jsonObjectType {
		return rustMessage{}, fmt.Errorf("only CUE object message constraints are supported in this version")
	}
	if object.AdditionalProperties != nil && *object.AdditionalProperties {
		return rustMessage{}, fmt.Errorf("open message objects are not supported yet")
	}
	var keywords map[string]json.RawMessage
	if err := json.Unmarshal(definition, &keywords); err != nil {
		return rustMessage{}, err
	}
	if err := rejectUnsupportedJSONKeywords(keywords, map[string]struct{}{
		jsonTypeKeyword: {}, jsonPropertiesKeyword: {}, jsonRequiredKeyword: {},
		jsonAdditionalPropertiesKeyword: {}, jsonTitleKeyword: {}, jsonDescriptionKeyword: {},
	}, "object constraint"); err != nil {
		return rustMessage{}, err
	}
	result := rustMessage{ID: message.ID}
	required := make(map[string]bool, len(object.Required))
	for _, name := range object.Required {
		required[name] = true
	}
	propertyNames := make([]string, 0, len(object.Properties))
	for name := range object.Properties {
		propertyNames = append(propertyNames, name)
	}
	sort.Strings(propertyNames)
	for _, name := range propertyNames {
		propertySchema, err := flattenSchema(object.Properties[name])
		if err != nil {
			return rustMessage{}, fmt.Errorf("field %q: %w", name, err)
		}
		field, err := parseRustMessageField(name, propertySchema, required[name])
		if err != nil {
			return rustMessage{}, err
		}
		result.Fields = append(result.Fields, field)
	}
	return result, nil
}

func parseRustMessageField(name string, rawSchema json.RawMessage, required bool) (rustMessageField, error) {
	var schema struct {
		Type      string             `json:"type"`
		Pattern   string             `json:"pattern"`
		MinLength *int64             `json:"minLength"`
		MaxLength *int64             `json:"maxLength"`
		Minimum   *json.Number       `json:"minimum"`
		Maximum   *json.Number       `json:"maximum"`
		Not       *jsonNotConstraint `json:"not"`
	}
	if err := json.Unmarshal(rawSchema, &schema); err != nil {
		return rustMessageField{}, err
	}
	var keywords map[string]json.RawMessage
	if err := json.Unmarshal(rawSchema, &keywords); err != nil {
		return rustMessageField{}, err
	}
	if err := rejectUnsupportedJSONKeywords(keywords, map[string]struct{}{
		jsonTypeKeyword: {}, jsonPatternKeyword: {}, jsonMinLengthKeyword: {}, jsonMaxLengthKeyword: {},
		jsonMinimumKeyword: {}, jsonMaximumKeyword: {}, jsonNotKeyword: {}, jsonTitleKeyword: {}, jsonDescriptionKeyword: {},
	}, fmt.Sprintf("field %q constraint", name)); err != nil {
		return rustMessageField{}, err
	}
	field := rustMessageField{Name: name, RustName: snakeCase(name), Required: required, Pattern: schema.Pattern}
	if field.RustName == "" {
		return rustMessageField{}, fmt.Errorf("field %q cannot be mapped to a Rust identifier", name)
	}
	if err := lowerRustMessageField(&field, jsonValueType(schema.Type), schema.Pattern, schema.MinLength, schema.MaxLength, schema.Minimum, schema.Maximum, schema.Not); err != nil {
		return rustMessageField{}, err
	}
	field.MinLength, field.MaxLength = schema.MinLength, schema.MaxLength
	return field, nil
}

func lowerRustMessageField(field *rustMessageField, valueType jsonValueType, pattern string, minLength, maxLength *int64, minimum, maximum *json.Number, not *jsonNotConstraint) error {
	switch valueType {
	case jsonStringType:
		if minimum != nil || maximum != nil {
			return fmt.Errorf("string field %q has numeric bounds that cannot be applied", field.Name)
		}
	case jsonIntegerType:
		if pattern != "" || minLength != nil || maxLength != nil || not != nil {
			return fmt.Errorf("integer field %q has a string-only constraint", field.Name)
		}
		if minimum == nil || maximum == nil {
			return fmt.Errorf("integer field %q must have both minimum and maximum bounds for Rust i64 lowering", field.Name)
		}
		min, err := strconv.ParseInt(minimum.String(), 10, 64)
		if err != nil {
			return fmt.Errorf("integer field %q minimum is outside Rust i64 range", field.Name)
		}
		max, err := strconv.ParseInt(maximum.String(), 10, 64)
		if err != nil {
			return fmt.Errorf("integer field %q maximum is outside Rust i64 range", field.Name)
		}
		if min > max {
			return fmt.Errorf("integer field %q has minimum greater than maximum", field.Name)
		}
		field.MinInt, field.MaxInt = &min, &max
	case jsonNumberType:
		return fmt.Errorf("number field %q is not supported yet; CUE number precision is not lowered to f64", field.Name)
	case jsonBooleanType:
		if pattern != "" || minLength != nil || maxLength != nil || minimum != nil || maximum != nil || not != nil {
			return fmt.Errorf("boolean field %q has unsupported value constraints", field.Name)
		}
	default:
		return fmt.Errorf("field %q has unsupported JSON Schema type %q", field.Name, valueType)
	}
	rustFieldType, err := rustType(valueType)
	if err != nil {
		return err
	}
	field.RustType = rustFieldType
	if not != nil {
		if valueType == jsonStringType && not.Const == "" {
			field.RejectEmpty = true
		} else {
			return fmt.Errorf("field %q uses an unsupported not constraint", field.Name)
		}
	}
	return nil
}

func rejectUnsupportedJSONKeywords(keywords map[string]json.RawMessage, allowed map[string]struct{}, description string) error {
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
		var currentType, nextType string
		_ = json.Unmarshal(current, &currentType)
		_ = json.Unmarshal(next, &nextType)
		if jsonValueType(currentType) == jsonNumberType && jsonValueType(nextType) == jsonIntegerType || jsonValueType(currentType) == jsonIntegerType && jsonValueType(nextType) == jsonNumberType {
			return json.RawMessage(strconv.Quote(string(jsonIntegerType))), nil
		}
		if currentType == nextType {
			return current, nil
		}
		return nil, fmt.Errorf("incompatible JSON Schema types %q and %q", currentType, nextType)
	case jsonMinimumKeyword, jsonMaximumKeyword:
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
	case jsonMinLengthKeyword, jsonMaxLengthKeyword:
		currentLength, currentErr := strconv.ParseInt(string(current), 10, 64)
		nextLength, nextErr := strconv.ParseInt(string(next), 10, 64)
		if currentErr != nil || nextErr != nil {
			return nil, fmt.Errorf("invalid JSON Schema length constraint")
		}
		if key == jsonMinLengthKeyword && currentLength >= nextLength || key == jsonMaxLengthKeyword && currentLength <= nextLength {
			return current, nil
		}
		return next, nil
	default:
		return nil, fmt.Errorf("multiple incompatible JSON Schema %q constraints are unsupported", key)
	}
}
