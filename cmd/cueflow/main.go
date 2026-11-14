package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/jcfangc/cue-flow/internal/backend"
	pythonbackend "github.com/jcfangc/cue-flow/internal/backend/python"
	rustbackend "github.com/jcfangc/cue-flow/internal/backend/rust"
	"github.com/jcfangc/cue-flow/internal/compiler"
)

type targetLanguage string

const (
	rustLanguage     targetLanguage = "rust"
	pythonLanguage   targetLanguage = "python"
	rustOutputPath                  = "./generated/cueflow.rs"
	pythonOutputPath                = "./generated/cueflow.py"
	endpointFlag                    = "endpoint"
	runtimeFlag                     = "runtime"
	transportFlag                   = "transport"
	codecFlag                       = "codec"
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
	var generate func(*compiler.Protocol, backend.GenerateOptions) (string, error)
	outputDefault := rustOutputPath
	if command == "generate" {
		if len(args) == 0 {
			return fmt.Errorf("usage: cueflow generate {rust|python} [flags]")
		}
		language := targetLanguage(args[0])
		args = args[1:]
		switch language {
		case rustLanguage:
			generate = rustbackend.GenerateWithOptions
		case pythonLanguage:
			generate = pythonbackend.GenerateWithOptions
			outputDefault = pythonOutputPath
		default:
			return fmt.Errorf("unsupported code generation language %q", language)
		}
	} else if command != "check" {
		return usageError()
	}

	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	input := flags.String("input", "./cue/examples", "directory containing the CUE package")
	output := flags.String("output", outputDefault, "generated source file path")
	endpoint := flags.String(
		endpointFlag,
		string(backend.BothEndpoints),
		"endpoint API to generate: client, server, or both",
	)
	runtime := flags.String(runtimeFlag, "", "async runtime, such as tokio or asyncio")
	transport := flags.String(transportFlag, "", "transport axis, such as websocket")
	codec := flags.String(codecFlag, "", "encoding axis, such as json")
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
		if hasFlag(flags, endpointFlag, runtimeFlag, transportFlag, codecFlag) {
			return fmt.Errorf(
				"--endpoint, --runtime, --transport, and --codec are only supported by generate",
			)
		}
		fmt.Println("protocol is valid")
		return nil
	}

	options := backend.GenerateOptions{
		Endpoint:  backend.Endpoint(*endpoint),
		Runtime:   backend.Runtime(*runtime),
		Transport: backend.Transport(*transport),
		Codec:     backend.Codec(*codec),
	}
	if err := options.Validate(); err != nil {
		return err
	}
	generated, err := generate(protocol, options)
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

func hasFlag(flags *flag.FlagSet, names ...string) bool {
	selected := make(map[string]struct{}, len(names))
	for _, name := range names {
		selected[name] = struct{}{}
	}
	found := false
	flags.Visit(func(value *flag.Flag) {
		if _, exists := selected[value.Name]; exists {
			found = true
		}
	})
	return found
}

func usageError() error {
	return fmt.Errorf(
		"usage: cueflow check [--input package-dir] | " +
			"cueflow generate {rust|python} [--input package-dir] [--output file] " +
			"[--runtime tokio|asyncio] [--transport websocket] [--codec json] " +
			"[--endpoint client|server|both]",
	)
}
