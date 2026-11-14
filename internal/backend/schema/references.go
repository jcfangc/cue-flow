// 文件职责：解析 CUE 导出的 JSON Schema 定义引用，并检测递归类型引用。
package schema

import (
	"encoding/json"
	"fmt"
	"strings"
)

func referencedDefinition(data []byte) (json.RawMessage, map[string]json.RawMessage, string, error) {
	var envelope struct {
		Ref  string                     `json:"$ref"`
		Defs map[string]json.RawMessage `json:"$defs"`
	}
	if err := json.Unmarshal(data, &envelope); err != nil {
		return nil, nil, "", err
	}
	name, ok := definitionName(envelope.Ref)
	if !ok {
		return nil, nil, "", fmt.Errorf("unsupported generated JSON Schema reference %q", envelope.Ref)
	}
	definition, ok := envelope.Defs[name]
	if !ok {
		return nil, nil, "", fmt.Errorf("unsupported generated JSON Schema reference %q", envelope.Ref)
	}
	return definition, envelope.Defs, name, nil
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
) (json.RawMessage, string, error) {
	var reference struct {
		Ref string `json:"$ref"`
	}
	if err := json.Unmarshal(raw, &reference); err != nil {
		return nil, "", err
	}
	if reference.Ref == "" {
		return raw, "", nil
	}
	var keywords map[string]json.RawMessage
	if err := json.Unmarshal(raw, &keywords); err != nil {
		return nil, "", err
	}
	for keyword := range keywords {
		if keyword == "$ref" || keyword == jsonTitleKeyword || keyword == jsonDescriptionKeyword {
			continue
		}
		return nil, "", fmt.Errorf("JSON Schema reference has unsupported sibling %q", keyword)
	}
	name, ok := definitionName(reference.Ref)
	if !ok {
		return nil, "", fmt.Errorf("unsupported generated JSON Schema reference %q", reference.Ref)
	}
	definition, ok := definitions[name]
	if !ok {
		return nil, "", fmt.Errorf("unsupported generated JSON Schema reference %q", reference.Ref)
	}
	return definition, name, nil
}
