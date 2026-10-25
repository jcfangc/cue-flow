// 文件职责：把共享消息字段模型写成 Pydantic 消息类及字段校验器。
// CUE 约束的通用解析在 backend/schema；Python 类型与 Field 参数在此处生成。
package python

import (
	"bytes"
	"fmt"
	"strconv"

	"github.com/jcfangc/cue-flow/internal/backend/schema"
)

func writeMessages(out *bytes.Buffer, names *pythonNames) error {
	out.WriteString("class _Message(BaseModel):\n    model_config = ConfigDict(strict=True, extra=\"forbid\", revalidate_instances=\"always\")\n\n")
	for _, message := range names.messages {
		if err := writeMessage(out, message, names); err != nil {
			return err
		}
	}
	return nil
}

func writeMessage(out *bytes.Buffer, message schema.Message, names *pythonNames) error {
	className := names.messageClasses[message.ID]
	fmt.Fprintf(out, "class %s(_Message):\n", className)
	if len(message.Fields) == 0 {
		out.WriteString("    pass\n\n")
		return nil
	}
	for _, field := range message.Fields {
		if err := writeMessageField(out, message.ID, field, names.fieldNames[message.ID][field.Name]); err != nil {
			return err
		}
	}
	for _, field := range message.Fields {
		if !field.Required {
			writeOptionalFieldValidator(out, field, names.fieldNames[message.ID][field.Name])
		}
	}
	out.WriteByte('\n')
	return nil
}

func writeMessageField(out *bytes.Buffer, messageID string, field schema.Field, fieldName string) error {
	lowered, err := pythonFieldType(field)
	if err != nil {
		return fmt.Errorf("message %q field %q: %w", messageID, field.Name, err)
	}
	if !field.Required {
		lowered.Type += " | None"
		lowered.Arguments = append([]string{"default=None"}, lowered.Arguments...)
	}
	lowered.Arguments = append([]string{"alias=" + strconv.Quote(field.Name)}, lowered.Arguments...)
	fmt.Fprintf(out, "    %s: %s = Field(%s)\n", fieldName, lowered.Type, join(lowered.Arguments, ", "))
	return nil
}

type pythonFieldLowering struct {
	Type      string
	Arguments []string
}

type pythonIntegerRange struct {
	Minimum int64
	Maximum int64
}

func pythonFieldType(field schema.Field) (pythonFieldLowering, error) {
	result := pythonFieldLowering{Arguments: make([]string, 0, 3)}
	switch field.Kind {
	case schema.String:
		minimumLength := field.MinLength
		if field.RejectEmpty && (minimumLength == nil || *minimumLength < 1) {
			minimum := int64(1)
			minimumLength = &minimum
		}
		if minimumLength != nil {
			result.Arguments = append(result.Arguments, fmt.Sprintf("min_length=%d", *minimumLength))
		}
		if field.MaxLength != nil {
			result.Arguments = append(result.Arguments, fmt.Sprintf("max_length=%d", *field.MaxLength))
		}
		if field.Pattern != "" {
			result.Arguments = append(result.Arguments, "pattern="+strconv.Quote(field.Pattern))
		}
		result.Type = "StrictStr"
		return result, nil
	case schema.Integer:
		bounds, err := pythonIntegerBounds(field)
		if err != nil {
			return pythonFieldLowering{}, err
		}
		result.Type = "StrictInt"
		result.Arguments = append(
			result.Arguments,
			fmt.Sprintf("ge=%d", bounds.Minimum),
			fmt.Sprintf("le=%d", bounds.Maximum),
		)
		return result, nil
	case schema.Boolean:
		result.Type = "StrictBool"
		return result, nil
	case schema.Number:
		return pythonFieldLowering{}, fmt.Errorf("number fields are not supported by the Python backend yet")
	default:
		return pythonFieldLowering{}, fmt.Errorf("field kind %q is not supported by the Python backend", field.Kind)
	}
}

func pythonIntegerBounds(field schema.Field) (pythonIntegerRange, error) {
	if field.Minimum == nil || field.Maximum == nil {
		return pythonIntegerRange{}, fmt.Errorf("integer fields need minimum and maximum bounds for cross-backend compatibility")
	}
	minimum, err := strconv.ParseInt(*field.Minimum, 10, 64)
	if err != nil {
		return pythonIntegerRange{}, fmt.Errorf("integer minimum is outside the supported i64 range")
	}
	maximum, err := strconv.ParseInt(*field.Maximum, 10, 64)
	if err != nil {
		return pythonIntegerRange{}, fmt.Errorf("integer maximum is outside the supported i64 range")
	}
	if minimum > maximum {
		return pythonIntegerRange{}, fmt.Errorf("integer minimum is greater than maximum")
	}
	return pythonIntegerRange{Minimum: minimum, Maximum: maximum}, nil
}

func writeOptionalFieldValidator(out *bytes.Buffer, field schema.Field, fieldName string) {
	fmt.Fprintf(out, "\n    @field_validator(%s, mode=\"before\")\n    @classmethod\n    def _reject_null_%s(cls, value: object) -> object:\n        if value is None:\n            raise ValueError(\"optional field cannot be null\")\n        return value\n", strconv.Quote(fieldName), fieldName)
}

func join(values []string, separator string) string {
	result := ""
	for index, value := range values {
		if index > 0 {
			result += separator
		}
		result += value
	}
	return result
}
