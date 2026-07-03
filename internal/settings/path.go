package settings

import (
	"fmt"
	"reflect"
	"strconv"
	"strings"
)

// findFieldByYamlTag returns the struct field whose yaml tag matches the given tag name.
// This handles the mismatch between Go field names (e.g. "CPUCores") and yaml tags (e.g. "cpu_cores").
func findFieldByYamlTag(v reflect.Value, tagName string) reflect.Value {
	for i := 0; i < v.NumField(); i++ {
		field := v.Type().Field(i)
		yamlTag := field.Tag.Get("yaml")
		// yaml tag format: "name,omitempty" or "name"
		if strings.HasPrefix(yamlTag, tagName) {
			return v.Field(i)
		}
	}
	return reflect.Value{}
}

// setByPath sets a value in settings by dotted-path string (e.g. "agent.default_driver").
func setByPath(s *Settings, keyPath, value string) error {
	parts := strings.Split(keyPath, ".")
	v := reflect.ValueOf(s).Elem()
	return setByReflect(v, parts, value)
}

// setByReflect walks a reflect.Value tree by dotted path parts and sets the leaf.
func setByReflect(v reflect.Value, parts []string, value string) error {
	if len(parts) == 0 {
		return fmt.Errorf("empty path")
	}

	// For nested structs, drill in.
	if len(parts) > 1 {
		f := findFieldByYamlTag(v, parts[0])
		if !f.IsValid() {
			return fmt.Errorf("unknown field %q in path", parts[0])
		}
		// If it's a struct, recurse.
		if f.Kind() == reflect.Struct {
			return setByReflect(f, parts[1:], value)
		}
		return fmt.Errorf("intermediate field %q is not a struct", parts[0])
	}

	// Leaf — set the value.
	f := findFieldByYamlTag(v, parts[0])
	if !f.IsValid() {
		return fmt.Errorf("unknown field %q", parts[0])
	}
	if !f.CanSet() {
		return fmt.Errorf("field %q is not settable", parts[0])
	}

	switch f.Kind() {
	case reflect.String:
		f.SetString(value)
	case reflect.Int:
		n, err := strconv.Atoi(value)
		if err != nil {
			return fmt.Errorf("invalid int %q: %w", value, err)
		}
		f.SetInt(int64(n))
	case reflect.Float64:
		n, err := strconv.ParseFloat(value, 64)
		if err != nil {
			return fmt.Errorf("invalid float %q: %w", value, err)
		}
		f.SetFloat(n)
	case reflect.Bool:
		b, err := strconv.ParseBool(value)
		if err != nil {
			return fmt.Errorf("invalid bool %q: %w", value, err)
		}
		f.SetBool(b)
	default:
		return fmt.Errorf("unsupported field type %s for %q", f.Kind(), parts[0])
	}
	return nil
}
