// 文件职责：验证 CUE 标量约束降级时对 JSON Schema const 的严格解释。
package schema

import (
	"encoding/json"
	"testing"
)

func TestValidateFieldConstraintEmptyString(t *testing.T) {
	field := Field{Name: "id", Kind: String}
	constraint := &jsonNotConstraint{Const: json.RawMessage(`""`)}
	if err := validateFieldConstraint(&field, nil, nil, constraint); err != nil {
		t.Fatalf("validateFieldConstraint() error = %v", err)
	}
	if !field.RejectEmpty {
		t.Fatal("empty-string const did not mark the field as rejecting empty values")
	}
}

func TestValidateFieldConstraintRejectsUnsupportedConstValues(t *testing.T) {
	testCases := []struct {
		Name  string
		Const string
	}{
		{Name: "non-empty string", Const: `"value"`},
		{Name: "number", Const: `0`},
		{Name: "null", Const: `null`},
	}
	for _, testCase := range testCases {
		t.Run(testCase.Name, func(t *testing.T) {
			field := Field{Name: "id", Kind: String}
			constraint := &jsonNotConstraint{Const: json.RawMessage(testCase.Const)}
			if err := validateFieldConstraint(&field, nil, nil, constraint); err == nil {
				t.Fatal("validateFieldConstraint() succeeded for an unsupported const value")
			}
		})
	}
}
