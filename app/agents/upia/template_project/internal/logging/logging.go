package logging

import (
	"context"

	"go.uber.org/zap"
)

type loggerKey struct{}

var fallbackLogger Logger

func init() {
	_ = Init(ReleaseConfig)
}

// Init the package with custom options.
func Init(cfg zap.Config) error {
	var err error
	fallbackLogger, err = newLogger(cfg)
	return err
}

type (
	// Logger minimize the interface for logging in this service
	Logger interface {
		Info(args ...interface{})
		Infof(template string, args ...interface{})

		Warn(args ...interface{})
		Warnf(template string, args ...interface{})

		Error(args ...interface{})
		Errorf(template string, args ...interface{})

		Fatal(args ...interface{})
		Fatalf(template string, args ...interface{})

		WithFields(fields map[string]interface{}) Logger
		WithField(k string, v interface{}) Logger
	}
)

// WithLogger return a new context with the logger injected
func WithLogger(ctx context.Context, logger Logger) context.Context {
	return context.WithValue(ctx, loggerKey{}, logger)
}

// WithFields is like WithField but for multiple fields
func WithFields(ctx context.Context, fields map[string]interface{}) (context.Context, Logger) {
	logger := FromContext(ctx).WithFields(fields)
	return WithLogger(ctx, logger), logger
}

// WithField inject new logger with given key-value pair, the return the
// new context and logger, this is a shortcut for get a Logger with method
// FromContext, add fields and inject it back to the context
func WithField(ctx context.Context, k string, v interface{}) (context.Context, Logger) {
	logger := FromContext(ctx).WithField(k, v)
	return WithLogger(ctx, logger), logger
}

// FromContext return the logger from a context if any,
// if no logger in context return the fallbackLogger
func FromContext(ctx context.Context) Logger {
	if l, ok := ctx.Value(loggerKey{}).(Logger); ok {
		return l
	}

	return fallbackLogger
}
