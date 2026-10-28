// Build-only, fail-closed application of the reviewed upstream JOSE backport.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func digest(data []byte) string { value := sha256.Sum256(data); return hex.EncodeToString(value[:]) }

func main() {
	if len(os.Args) != 3 { panic("usage: harden_jose manifest module-directory") }
	data, err := os.ReadFile(os.Args[1]); if err != nil { panic(err) }
	var record struct {
		Notice string `json:"notice"`
		Files []struct {
			Path string `json:"path"`
			Original string `json:"original_sha256"`
			Patched string `json:"patched_sha256"`
			Replacements []struct { Old string; New string }
		}
	}
	if err := json.Unmarshal(data, &record); err != nil { panic(err) }
	if len(record.Files) != 4 { panic("unexpected patch file count") }
	for _, file := range record.Files {
		if filepath.Base(file.Path) != file.Path { panic("invalid patch path") }
		path := filepath.Join(os.Args[2], file.Path)
		original, err := os.ReadFile(path); if err != nil { panic(err) }
		if digest(original) != file.Original { panic("upstream source mismatch: " + file.Path) }
		source := string(original)
		for _, edit := range file.Replacements {
			if strings.Count(source, edit.Old) != 1 { panic("patch context mismatch: " + file.Path) }
			source = strings.Replace(source, edit.Old, edit.New, 1)
		}
		patched := []byte(record.Notice + source)
		if digest(patched) != file.Patched { panic("patched source mismatch: " + file.Path) }
		if err := os.WriteFile(path, patched, 0644); err != nil { panic(err) }
		fmt.Println(file.Path + " " + file.Patched)
	}
}
