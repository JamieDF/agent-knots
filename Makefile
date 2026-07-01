# agentjam Makefile
#
# Common development tasks. See CONTRIBUTING.md for the full development
# workflow.

.PHONY: help all build test test-race vet lint clean install run tidy fmt check

# Default target.
all: build test

help:
	@echo "agentjam — common targets:"
	@echo "  make build      - compile the agentjam binary"
	@echo "  make test       - run tests"
	@echo "  make test-race  - run tests with race detector"
	@echo "  make cover      - run tests with coverage"
	@echo "  make vet        - run go vet"
	@echo "  make lint       - run golangci-lint (requires install)"
	@echo "  make fmt        - run gofmt"
	@echo "  make tidy       - run go mod tidy"
	@echo "  make check      - vet + fmt check (no modifications)"
	@echo "  make install    - install to \$$GOPATH/bin"
	@echo "  make run ARGS=.. - build and run with args"
	@echo "  make clean      - remove build artifacts"

build:
	go build ./...

test:
	go test ./...

test-race:
	go test -race ./...

cover:
	go test -coverprofile=coverage.out ./...
	go tool cover -html=coverage.out -o coverage.html

vet:
	go vet ./...

fmt:
	gofmt -s -w .

tidy:
	go mod tidy

check:
	@test -z "$$(gofmt -l . | tee /dev/stderr)"
	go vet ./...

lint:
	@which golangci-lint > /dev/null || { echo "golangci-lint not installed"; exit 1; }
	golangci-lint run

install:
	go install ./cmd/agentjam

run: build
	./agentjam $(ARGS)

clean:
	rm -f agentjam coverage.out coverage.html