// 文件职责：解析 CUE 导出的 JSON Schema 定义引用，并检测递归类型引用。
package schema

import (
	"encoding/json"
	"fmt"
	"strings"
)

const unsupportedGeneratedSchemaReference = "unsupported generated JSON Schema reference %q"

type schemaDefinition struct {
	Root        json.RawMessage
	Definitions map[string]json.RawMessage
	RootName    string
}

type resolvedReference struct {
	Schema json.RawMessage
	Name   string
}

func referencedDefinition(data []byte) (schemaDefinition, error) {
	var envelope struct {
		Ref  string                     `json:"$ref"`
		Defs map[string]json.RawMessage `json:"$defs"`
	}
	if err := json.Unmarshal(data, &envelope); err != nil {
		return schemaDefinition{}, err
	}
	name, ok := definitionName(envelope.Ref)
	if !ok {
		return schemaDefinition{}, fmt.Errorf(unsupportedGeneratedSchemaReference, envelope.Ref)
	}
	definition, ok := envelope.Defs[name]
	if !ok {
		return schemaDefinition{}, fmt.Errorf(unsupportedGeneratedSchemaReference, envelope.Ref)
	}
	return schemaDefinition{
		Root:        definition,
		Definitions: envelope.Defs,
		RootName:    name,
	}, nil
}

func definitionName(reference string) (string, bool) {
	const definitionsPrefix = "#/$defs/"
	if !strings.HasPrefix(reference, definitionsPrefix) {
		return "", false
	}
	name := strings.TrimPrefix(reference, definitionsPrefix)
	return name, name != ""
}

func resolveReference(
	raw json.RawMessage,
	definitions map[string]json.RawMessage,
) (resolvedReference, error) {
	var reference struct {
		Ref string `json:"$ref"`
	}
	if err := json.Unmarshal(raw, &reference); err != nil {
		return resolvedReference{}, err
	}
	if reference.Ref == "" {
		return resolvedReference{Schema: raw}, nil
	}
	var keywords map[string]json.RawMessage
	if err := json.Unmarshal(raw, &keywords); err != nil {
		return resolvedReference{}, err
	}
	for keyword := range keywords {
		if keyword == "$ref" || keyword == jsonTitleKeyword || keyword == jsonDescriptionKeyword {
			continue
		}
		return resolvedReference{}, fmt.Errorf("JSON Schema reference has unsupported sibling %q", keyword)
	}
	name, ok := definitionName(reference.Ref)
	if !ok {
		return resolvedReference{}, fmt.Errorf(unsupportedGeneratedSchemaReference, reference.Ref)
	}
	definition, ok := definitions[name]
	if !ok {
		return resolvedReference{}, fmt.Errorf(unsupportedGeneratedSchemaReference, reference.Ref)
	}
	return resolvedReference{Schema: definition, Name: name}, nil
}
