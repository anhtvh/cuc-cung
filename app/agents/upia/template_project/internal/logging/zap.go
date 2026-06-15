package logging

import (
	"fmt"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

var (
	ReleaseConfig = zap.Config{
		Level:       zap.NewAtomicLevelAt(zap.InfoLevel),
		Development: false,
		Sampling: &zap.SamplingConfig{
			Initial:    100,
			Thereafter: 100,
		},
		Encoding: "json",
		EncoderConfig: zapcore.EncoderConfig{
			TimeKey:        "time",
			LevelKey:       "level",
			NameKey:        "logger",
			CallerKey:      "caller",
			FunctionKey:    zapcore.OmitKey,
			MessageKey:     "msg",
			LineEnding:     zapcore.DefaultLineEnding,
			EncodeLevel:    zapcore.LowercaseLevelEncoder,
			EncodeTime:     zapcore.RFC3339NanoTimeEncoder,
			EncodeDuration: zapcore.SecondsDurationEncoder,
			EncodeCaller:   zapcore.ShortCallerEncoder,
		},
		OutputPaths:      []string{"stdout"},
		ErrorOutputPaths: []string{"stdout"},
	}
)

type logger struct {
	*zap.SugaredLogger
}

// WithFields adds a variadic number of fields to the logging context and return new logger.
// Example:
//	logger.WithFields(Fields{
//		"hello": "world",
// 		"error", errors.New("http timeout"),
//     	"count", 42,
//	})
func (l *logger) WithFields(fields map[string]interface{}) Logger {
	var args []interface{}
	for k, v := range fields {
		args = append(args, k)
		args = append(args, v)
	}

	return &logger{SugaredLogger: l.SugaredLogger.With(args...)}
}

// WithField adds a field to the logging context and return new logger.
// Example:
//	logger.WithField("count", 42)
func (l *logger) WithField(k string, v interface{}) Logger {
	return l.WithFields(map[string]interface{}{k: v})
}

func newLogger(cfg zap.Config) (*logger, error) {
	z, err := cfg.Build()
	if err != nil {
		return nil, fmt.Errorf("logging: create logger failed: %w", err)
	}

	return &logger{SugaredLogger: z.Sugar()}, nil
}
