# Contributing to agent-knots

Thanks for your interest in contributing! agent-knots is a young project and
contributions of all kinds are welcome — code, documentation, bug reports,
feature ideas.

## Code of conduct

Be respectful, assume good faith, focus on the technical. We follow the
[Go community code of conduct](https://golang.org/conduct).

## Where to start

- **Look at the issue tracker.** Issues tagged
  [`good first issue`](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
  are scoped for newcomers.
- **Read [`docs/architecture.md`](docs/architecture.md).** Understanding
  the architecture is essential before changing interfaces.
- **Run the tests.** `go test ./...` should pass on `main`. If it doesn't,
  that's a bug — please open an issue.

## Development setup

```bash
git clone https://github.com/jamiedf/agent-knots.git
cd agent-knots
go test ./...
go build -o agent-knots ./cmd/agent-knots
```

You'll need Go 1.23+ (the project uses `go 1.23.4` in `go.mod`; the toolchain
directive in `go.mod` will fetch newer versions as needed).

For OpenCode work, install OpenCode: <https://opencode.ai>. For Podman
work, install Podman: <https://podman.io>.

## Project layout

See [`docs/architecture.md`](docs/architecture.md#package-layout) for the
full layout. The short version:

- `cmd/agent-knots/` — CLI commands (one file per subcommand)
- `internal/<package>/` — implementation (locked from external import)
- `internal/<package>/filestore/` — file-backed implementations
- `modes/` — default mode markdown files
- `docs/` — architecture, contributing, etc.

## Coding conventions

### Style

We follow standard Go style:

- `gofmt` (no exceptions)
- `go vet ./...` clean
- `golangci-lint run` clean (CI uses this)

### Naming

- Packages are short, lowercase, single-word where possible.
- Interfaces end in `-er` (`Driver`, `Store`, `Vault`, `Runtime`).
- Implementations are named by what they back the interface with
  (`FileStore`, `Podman`, `OpenCode`).
- Tests live next to the code they test (`foo.go` + `foo_test.go`).

### Errors

Use the sentinels in [`internal/errs`](internal/errs/) for failure modes
callers care about (`ErrNotFound`, `ErrAlreadyExists`, etc.). Wrap with
`errs.Wrap` so the sentinel is preserved:

```go
if err != nil {
    return errs.Wrap(err, "loading %s", name)
}
```

Callers should compare with `errs.Is` (alias for `errors.Is`):

```go
if errs.Is(err, errs.ErrNotFound) {
    // not-found handling
}
```

### Context

Every I/O method takes `ctx context.Context` as its first argument and
respects cancellation. The pattern:

```go
func (s *Store) Get(ctx context.Context, id ID) (*Thing, error) {
    if err := ctx.Err(); err != nil {
        return nil, err
    }
    // ... do the work, passing ctx through ...
}
```

### Concurrency

All exported methods on stores, drivers, runtimes, and the vault must be
safe for concurrent use. Use `sync.RWMutex` for read-heavy data, document
thread-safety expectations in package doc.

### Tests

We use table-driven tests with subtests:

```go
func TestParseBytes(t *testing.T) {
    cases := []struct {
        name string
        in   string
        want int64
    }{
        {"zero", "0", 0},
        {"with unit", "1KB", 1024},
    }
    for _, c := range cases {
        t.Run(c.name, func(t *testing.T) {
            got, err := parseBytes(c.in)
            if err != nil {
                t.Fatal(err)
            }
            if got != c.want {
                t.Errorf("got %d, want %d", got, c.want)
            }
        })
    }
}
```

Where it adds clarity, add a `// Example...` function (these show up in
godoc and pkg.go.dev):

```go
func ExampleWrap() {
    err := errs.Wrap(errs.ErrNotFound, "loading %q", "x")
    if errors.Is(err, errs.ErrNotFound) {
        fmt.Println("not found")
    }
    // Output: not found
}
```

### Documentation

Every exported package, type, function, and method gets a godoc comment
starting with the name:

```go
// Package foo provides ...
package foo

// Thing is a ...
type Thing struct { ... }

// Get returns the Thing by ID.
func (s *Store) Get(ctx context.Context, id ID) (*Thing, error) { ... }
```

The first sentence of a godoc comment should be a complete summary.

## Pull request process

1. **Open an issue first** for non-trivial changes. Discuss the approach
   before writing code.
2. **Fork the repo** and create a branch from `main`.
3. **Write tests.** PRs without tests are unlikely to merge.
4. **Update docs** if you're changing user-facing behavior. The README,
   architecture doc, and godoc comments all matter.
5. **Run the full test suite** before pushing:
   ```bash
   go test -race -cover ./...
   go vet ./...
   golangci-lint run
   ```
6. **One logical change per commit.** Squash fixup commits. Write commit
   messages in the imperative mood ("Add vault template parser", not
   "Added").
7. **Open a PR** against `main`. The CI will run tests on Linux, macOS,
   and Windows. Address review feedback before merge.

## Release process

We use [Semantic Versioning](https://semver.org/). Versions are tagged
manually after a successful main-branch CI run:

```bash
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

The release workflow builds binaries for all supported platforms and
publishes them on the GitHub release page. See `.github/workflows/release.yml`.

## Decision records

Significant architectural decisions are recorded as ADRs in
[`docs/decisions/`](docs/decisions/). Each ADR explains the context,
options considered, and the chosen approach. Read these before proposing
changes that affect core interfaces.

## License

By contributing, you agree that your contributions will be licensed under
the [MIT License](LICENSE).

## Getting help

- **GitHub Issues** for bugs and feature requests
- **GitHub Discussions** for questions and design discussion
- **Code review** on your PR — open one early, even as a draft

We're a small project, so responses may take a day or two. Patience is
appreciated. 🙏