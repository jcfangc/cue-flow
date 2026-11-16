// 文件职责：生成 Rust 消息类型、嵌套结构和 CUE 约束校验逻辑。
// 字段的 Rust 类型与名称分别由 schema.go 和 names.go 降级。
package rust

import (
	"bytes"
	"fmt"
	"strconv"

	"github.com/jcfangc/cue-flow/internal/backend/schema"
)

func writeMessages(out *bytes.Buffer, messages []rustMessage) error {
	out.WriteString("pub mod messages {\n\n")
	for _, message := range messages {
		writeMessage(out, message)
	}
	out.WriteString("}\n\n")
	return nil
}

func writeMessage(out *bytes.Buffer, message rustMessage) {
	for _, field := range message.Fields {
		writeNestedMessageTypes(out, field)
	}
	writeMessageStruct(out, message.TypeName, message.Fields)
}

func writeNestedMessageTypes(out *bytes.Buffer, field rustMessageField) {
	if field.Kind != schema.Object {
		return
	}
	for _, child := range field.Fields {
		writeNestedMessageTypes(out, child)
	}
	writeMessageStruct(out, field.TypeName, field.Fields)
}

func writeMessageStruct(out *bytes.Buffer, typeName string, fields []rustMessageField) {
	fmt.Fprintf(out, "    #[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]\n    #[serde(deny_unknown_fields)]\n    pub struct %s {\n", typeName)
	for _, field := range fields {
		writeMessageField(out, field)
	}
	out.WriteString("    }\n\n")
	fmt.Fprintf(out, "    impl %s {\n        pub fn validate(&self) -> std::result::Result<(), super::ValidationError> {\n", typeName)
	for _, field := range fields {
		writeFieldValidation(out, field)
	}
	out.WriteString("            Ok(())\n        }\n    }\n\n")
}

func writeMessageField(out *bytes.Buffer, field rustMessageField) {
	typ := field.RustType
	if !field.Required {
		typ = "Option<" + typ + ">"
	}
	if field.Required {
		fmt.Fprintf(out, "        #[serde(rename = %s)]\n        pub %s: %s,\n", strconv.Quote(field.Name), field.RustName, typ)
		return
	}
	// Optional CUE fields should be omitted on the wire when absent.
	fmt.Fprintf(out, "        #[serde(rename = %s, default, deserialize_with = \"super::deserialize_present\", skip_serializing_if = \"Option::is_none\")]\n        pub %s: %s,\n", strconv.Quote(field.Name), field.RustName, typ)
}

func writeFieldValidation(out *bytes.Buffer, field rustMessageField) {
	if field.Kind == schema.List {
		writeListFieldValidation(out, field)
		return
	}
	if field.Kind == schema.Object {
		writeNestedFieldValidation(out, field)
		return
	}
	if !field.RejectEmpty && field.Pattern == "" && field.MinLength == nil && field.MaxLength == nil && field.MinInt == nil {
		return
	}
	access := "self." + field.RustName
	indentation := "            "
	if !field.Required {
		fmt.Fprintf(out, "            if let Some(value) = %s.as_ref() {\n", access)
		access = "value"
		indentation = "                "
	}
	writeStringValidation(out, field, access, indentation)
	writeIntegerValidation(out, field, access)
	if !field.Required {
		out.WriteString("            }\n")
	}
}

func writeListFieldValidation(out *bytes.Buffer, field rustMessageField) {
	if field.Items == nil {
		return
	}
	item := *field.Items
	if !item.RejectEmpty && item.Pattern == "" && item.MinLength == nil && item.MaxLength == nil {
		return
	}
	values := "self." + field.RustName
	loopIndentation := "            "
	itemIndentation := "                "
	if !field.Required {
		values = "values"
		fmt.Fprintf(out, "            if let Some(values) = self.%s.as_ref() {\n", field.RustName)
		loopIndentation = "                "
		itemIndentation = "                    "
	}
	fmt.Fprintf(out, "%sfor item in %s {\n", loopIndentation, values)
	writeStringValidation(out, item, "item", itemIndentation)
	fmt.Fprintf(out, "%s}\n", loopIndentation)
	if !field.Required {
		out.WriteString("            }\n")
	}
}

func writeNestedFieldValidation(out *bytes.Buffer, field rustMessageField) {
	if field.Required {
		fmt.Fprintf(out, "            self.%s.validate()?;\n", field.RustName)
		return
	}
	fmt.Fprintf(out, "            if let Some(value) = self.%s.as_ref() { value.validate()?; }\n", field.RustName)
}

func writeStringValidation(out *bytes.Buffer, field rustMessageField, access, indentation string) {
	if field.RejectEmpty {
		fmt.Fprintf(out, "%sif %s.is_empty() { return Err(super::ValidationError::Empty(%s)); }\n", indentation, access, strconv.Quote(field.Name))
	}
	if field.Pattern != "" {
		fmt.Fprintf(out, "%slet pattern = regex::Regex::new(%s).map_err(|_| super::ValidationError::PatternCompile(%s))?;\n%sif !pattern.is_match(&%s) { return Err(super::ValidationError::Pattern { field: %s, pattern: %s }); }\n",
			indentation, strconv.Quote(field.Pattern), strconv.Quote(field.Name), indentation, access, strconv.Quote(field.Name), strconv.Quote(field.Pattern))
	}
	if field.MinLength != nil || field.MaxLength != nil {
		min := "None"
		max := "None"
		if field.MinLength != nil {
			min = fmt.Sprintf("Some(%d)", *field.MinLength)
		}
		if field.MaxLength != nil {
			max = fmt.Sprintf("Some(%d)", *field.MaxLength)
		}
		fmt.Fprintf(out, "%slet length = %s.chars().count();\n%sif %s || %s { return Err(super::ValidationError::Length { field: %s, min: %s, max: %s }); }\n",
			indentation,
			access,
			indentation,
			lengthComparison(access, field.MinLength, true),
			lengthComparison(access, field.MaxLength, false),
			strconv.Quote(field.Name), min, max)
	}
}

func writeIntegerValidation(out *bytes.Buffer, field rustMessageField, access string) {
	if field.MinInt == nil || field.MaxInt == nil {
		return
	}
	numericAccess := access
	if !field.Required {
		numericAccess = "*" + access
	}
	fmt.Fprintf(out, "                if %s < %d || %s > %d { return Err(super::ValidationError::IntegerRange { field: %s, min: %d, max: %d }); }\n",
		numericAccess, *field.MinInt, numericAccess, *field.MaxInt, strconv.Quote(field.Name), *field.MinInt, *field.MaxInt)
}

func lengthComparison(access string, bound *int64, minimum bool) string {
	if bound == nil {
		return "false"
	}
	if minimum {
		return fmt.Sprintf("length < %d", *bound)
	}
	return fmt.Sprintf("length > %d", *bound)
}
