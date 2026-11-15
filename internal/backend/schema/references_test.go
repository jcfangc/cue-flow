// 文件职责：验证生成 JSON Schema 定义引用的解析规则和边界错误。
package schema

import (
	"encoding/json"
	"strings"
	"testing"
)

const (
	testDefinitionReference = "#/$defs/Query"
	testDefinitionSchema    = `{"type":"object"}`
)

func TestDefinitionName(t *testing.T) {
	testCases := []struct {
		Name      string
		Reference string
		WantName  string
		WantValid bool
	}{
		{Name: "generated local definition", Reference: testDefinitionReference, WantName: "Query", WantValid: true},
		{Name: "empty definition name", Reference: "#/$defs/", WantValid: false},
		{Name: "external reference", Reference: "https://example.test/schema#/$defs/Query", WantValid: false},
		{Name: "unsupported local path", Reference: "#/definitions/Query", WantValid: false},
	}
	for _, testCase := range testCases {
		t.Run(testCase.Name, func(t *testing.T) {
			name, valid := definitionName(testCase.Reference)
			if name != testCase.WantName || valid != testCase.WantValid {
				t.Fatalf("definitionName(%q) = (%q, %t), want (%q, %t)",
					testCase.Reference, name, valid, testCase.WantName, testCase.WantValid)
			}
		})
	}
}

func TestReferencedDefinition(t *testing.T) {
	data := []byte(`{"$ref":"#/$defs/Query","$defs":{"Query":{"type":"object"}}}`)
	definition, err := referencedDefinition(data)
	if err != nil {
		t.Fatalf("referencedDefinition() error = %v", err)
	}
	if string(definition.Root) != testDefinitionSchema {
		t.Fatalf("root = %s, want %s", definition.Root, testDefinitionSchema)
	}
	if definition.RootName != "Query" {
		t.Fatalf("root name = %q, want Query", definition.RootName)
	}
	if len(definition.Definitions) != 1 {
		t.Fatalf("definition count = %d, want 1", len(definition.Definitions))
	}
}

func TestReferencedDefinitionRejectsUnsupportedOrMissingReference(t *testing.T) {
	testCases := []struct {
		Name string
		Data string
	}{
		{Name: "unsupported reference", Data: `{"$ref":"#/definitions/Query"}`},
		{Name: "missing definition", Data: `{"$ref":"#/$defs/Query","$defs":{}}`},
	}
	for _, testCase := range testCases {
		t.Run(testCase.Name, func(t *testing.T) {
			_, err := referencedDefinition([]byte(testCase.Data))
			if err == nil || !strings.Contains(err.Error(), "unsupported generated JSON Schema reference") {
				t.Fatalf("referencedDefinition() error = %v, want unsupported reference", err)
			}
		})
	}
}

func TestResolveReference(t *testing.T) {
	definitions := map[string]json.RawMessage{"Query": []byte(testDefinitionSchema)}
	testCases := []struct {
		Name          string
		Raw           string
		WantSchema    string
		WantName      string
		WantErrorText string
	}{
		{Name: "inline schema", Raw: `{"type":"string"}`, WantSchema: `{"type":"string"}`},
		{
			Name:       "reference with documentation siblings",
			Raw:        `{"$ref":"#/$defs/Query","title":"Query","description":"request"}`,
			WantSchema: testDefinitionSchema,
			WantName:   "Query",
		},
		{
			Name:          "unsupported sibling",
			Raw:           `{"$ref":"#/$defs/Query","default":{}}`,
			WantErrorText: "unsupported sibling",
		},
		{
			Name:          "unsupported reference path",
			Raw:           `{"$ref":"#/definitions/Query"}`,
			WantErrorText: "unsupported generated JSON Schema reference",
		},
		{
			Name:          "missing definition",
			Raw:           `{"$ref":"#/$defs/Missing"}`,
			WantErrorText: "unsupported generated JSON Schema reference",
		},
	}
	for _, testCase := range testCases {
		t.Run(testCase.Name, func(t *testing.T) {
			result, err := resolveReference(json.RawMessage(testCase.Raw), definitions)
			if testCase.WantErrorText != "" {
				if err == nil || !strings.Contains(err.Error(), testCase.WantErrorText) {
					t.Fatalf("resolveReference() error = %v, want %q", err, testCase.WantErrorText)
				}
				return
			}
			if err != nil {
				t.Fatalf("resolveReference() error = %v", err)
			}
			if string(result.Schema) != testCase.WantSchema || result.Name != testCase.WantName {
				t.Fatalf("resolveReference() = (%s, %q), want (%s, %q)",
					result.Schema, result.Name, testCase.WantSchema, testCase.WantName)
			}
		})
	}
}
