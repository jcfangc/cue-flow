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
	for _, field := range message.Fields {
		if err := writeNestedModel(out, message.ID, field, fieldPath("", field.Name), names); err != nil {
			return err
		}
	}
	return writeModel(out, message.ID, names.messageClasses[message.ID], "", message.Fields, names)
}

func writeNestedModel(out *bytes.Buffer, messageID string, field schema.Field, path string, names *pythonNames) error {
	if field.Kind != schema.Object {
		return nil
	}
	for _, child := range field.Fields {
		if err := writeNestedModel(out, messageID, child, fieldPath(path, child.Name), names); err != nil {
			return err
		}
	}
	return writeModel(out, messageID, names.nestedTypeNames[messageID][path], path, field.Fields, names)
}

func writeModel(out *bytes.Buffer, messageID, className, parentPath string, fields []schema.Field, names *pythonNames) error {
	fmt.Fprintf(out, "class %s(_Message):\n", className)
	if len(fields) == 0 {
		out.WriteString("    pass\n\n")
		return nil
	}
	for _, field := range fields {
		path := fieldPath(parentPath, field.Name)
		if err := writeMessageField(out, messageID, field, path, names); err != nil {
			return fmt.Errorf("message %q field %q: %w", messageID, path, err)
		}
	}
	for _, field := range fields {
		if !field.Required {
			fieldName := names.fieldNames[messageID][fieldPath(parentPath, field.Name)]
			writeOptionalFieldValidator(out, field, fieldName)
		}
	}
	out.WriteByte('\n')
	return nil
}

func writeMessageField(out *bytes.Buffer, messageID string, field schema.Field, path string, names *pythonNames) error {
	fieldName := names.fieldNames[messageID][path]
	lowered, err := pythonFieldType(field, names.nestedTypeNames[messageID][path])
	if err != nil {
		return err
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

func pythonFieldType(field schema.Field, nestedTypeName string) (pythonFieldLowering, error) {
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
	case schema.Object:
		if nestedTypeName == "" {
			return pythonFieldLowering{}, fmt.Errorf("nested object field %q has no generated model", field.Name)
		}
		result.Type = nestedTypeName
		return result, nil
	case schema.List:
		if field.Items == nil || field.Items.Kind != schema.String {
			return pythonFieldLowering{}, fmt.Errorf("list field %q requires supported string items", field.Name)
		}
		item, err := pythonFieldType(*field.Items, "")
		if err != nil {
			return pythonFieldLowering{}, err
		}
		if len(item.Arguments) == 0 {
			result.Type = "list[" + item.Type + "]"
			return result, nil
		}
		result.Type = "list[Annotated[" + item.Type + ", Field(" + join(item.Arguments, ", ") + ")]]"
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
