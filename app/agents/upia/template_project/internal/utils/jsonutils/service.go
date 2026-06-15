package jsonutils

import (
	"encoding/json"

	"golang.org/x/text/unicode/norm"
)

// ToJSONString ...
func ToJSONString(v interface{}) string {
	b, err := json.Marshal(v)
	if err != nil {
		return ""
	}
	return string(b)
}
func FromJsonString(input string, output interface{}) error {
	if err := json.Unmarshal([]byte(input), output); err != nil {
		return err
	}
	return nil
}
func Normalize(src string) string {
	wc := norm.NFKC.Bytes([]byte(src))
	return string(wc)
}
