package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	rustbackend "github.com/jcfangc/cue-flow/internal/backend/rust"
	"github.com/jcfangc/cue-flow/internal/compiler"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "cueflow:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return usageError()
	}

	command := args[0]
	args = args[1:]
	var generate func(*compiler.Protocol) (string, error)
	if command == "generate" {
		if len(args) == 0 {
			return fmt.Errorf("usage: cueflow generate rust [flags]")
		}
		language := args[0]
		args = args[1:]
		switch language {
		case "rust":
			generate = rustbackend.Generate
		default:
			return fmt.Errorf("unsupported code generation language %q", language)
		}
	} else if command != "check" {
		return usageError()
	}

	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	input := flags.String("input", "./cue/examples", "directory containing the CUE package")
	output := flags.String("output", "./generated/cueflow.rs", "Rust output path (generate rust only)")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected arguments: %v", flags.Args())
	}

	inputDir, err := filepath.Abs(*input)
	if err != nil {
		return err
	}
	protocol, err := compiler.Load(inputDir)
	if err != nil {
		return err
	}
	if err := compiler.Check(protocol); err != nil {
		return err
	}
	if command == "check" {
		fmt.Println("protocol is valid")
		return nil
	}

	generated, err := generate(protocol)
	if err != nil {
		return err
	}
	outputPath, err := filepath.Abs(*output)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(outputPath, []byte(generated), 0o644); err != nil {
		return err
	}
	fmt.Println(outputPath)
	return nil
}

func usageError() error {
	return fmt.Errorf("usage: cueflow check [--input package-dir] | cueflow generate rust [--input package-dir] [--output file]")
}
