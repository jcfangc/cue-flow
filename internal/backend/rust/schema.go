// 文件职责：把共享消息 schema 转成 Rust 字段类型和 Rust 可实现的校验边界。
// 这里处理 Rust 特有限制（例如整数必须适配 i64）；通用 CUE/schema 解析位于 backend/schema。
package rust

import (
	"fmt"
	"strconv"

	"cuelang.org/go/cue"
	"github.com/jcfangc/cue-flow/internal/backend/schema"
	"github.com/jcfangc/cue-flow/internal/compiler"
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

type rustFieldLowering struct {
	RustType string
	MinInt   *int64
	MaxInt   *int64
}

type rustIntegerRange struct {
	Minimum int64
	Maximum int64
}

func parseRustMessage(ctx *cue.Context, message compiler.Message) (rustMessage, error) {
	common, err := schema.LowerMessage(ctx, message)
	if err != nil {
		return rustMessage{}, err
	}
	result := rustMessage{ID: common.ID}
	for _, field := range common.Fields {
		lowered, err := lowerRustField(field)
		if err != nil {
			return rustMessage{}, fmt.Errorf("field %q: %w", field.Name, err)
		}
		result.Fields = append(result.Fields, rustMessageField{
			Name: field.Name, RustName: snakeCase(field.Name), RustType: lowered.RustType,
			Required: field.Required, RejectEmpty: field.RejectEmpty, Pattern: field.Pattern,
			MinLength: field.MinLength, MaxLength: field.MaxLength,
			MinInt: lowered.MinInt, MaxInt: lowered.MaxInt,
		})
	}
	return result, nil
}

func lowerRustField(field schema.Field) (rustFieldLowering, error) {
	switch field.Kind {
	case schema.String:
		return rustFieldLowering{RustType: "String"}, nil
	case schema.Integer:
		rangeValue, err := rustIntegerBounds(field)
		if err != nil {
			return rustFieldLowering{}, err
		}
		return rustFieldLowering{
			RustType: "i64",
			MinInt:   &rangeValue.Minimum,
			MaxInt:   &rangeValue.Maximum,
		}, nil
	case schema.Boolean:
		return rustFieldLowering{RustType: "bool"}, nil
	case schema.Number:
		return rustFieldLowering{}, fmt.Errorf("number fields are not supported yet; CUE number precision is not lowered to f64")
	default:
		return rustFieldLowering{}, fmt.Errorf("unsupported field kind %q", field.Kind)
	}
}

func rustIntegerBounds(field schema.Field) (rustIntegerRange, error) {
	if field.Minimum == nil || field.Maximum == nil {
		return rustIntegerRange{}, fmt.Errorf("integer field must have both minimum and maximum bounds for Rust i64 lowering")
	}
	minimum, err := strconv.ParseInt(*field.Minimum, 10, 64)
	if err != nil {
		return rustIntegerRange{}, fmt.Errorf("integer minimum is outside Rust i64 range")
	}
	maximum, err := strconv.ParseInt(*field.Maximum, 10, 64)
	if err != nil {
		return rustIntegerRange{}, fmt.Errorf("integer maximum is outside Rust i64 range")
	}
	if minimum > maximum {
		return rustIntegerRange{}, fmt.Errorf("integer field has minimum greater than maximum")
	}
	return rustIntegerRange{Minimum: minimum, Maximum: maximum}, nil
}
