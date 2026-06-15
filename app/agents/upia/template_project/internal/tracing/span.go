package tracing

import (
	"context"
	"fmt"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/trace"
)

// This below functions using with context,
// when using those function you don't hesitate about libs

// StartSpan creates a span and a context.Context containing the newly-created span.
func StartSpan(ctx context.Context, name string) context.Context {
	tr := otel.Tracer("")
	start, _ := tr.Start(ctx, name)
	return start
}

// EndSpan finishes the span that is associated with the given context
func EndSpan(ctx context.Context) {
	s := trace.SpanFromContext(ctx)
	s.End()
}

// SpanID returns span identity associated with the given context
// return "" if there is no trace associated
func SpanID(ctx context.Context) string {
	s := trace.SpanFromContext(ctx)
	return s.SpanContext().SpanID().String()
}

// TraceID returns trace identity associated with the given context
// return "" if there is no trace associated
func TraceID(ctx context.Context) string {
	s := trace.SpanFromContext(ctx)
	return s.SpanContext().TraceID().String()
}

// SetAttribute set span attribute into span in context
// if context content no span, do nothing
func SetAttribute(ctx context.Context, key string, value interface{}) {
	s := trace.SpanFromContext(ctx)
	s.SetAttributes(makeAttribute(key, value))
}

// SetAttributes set span attribute into span in context
// if context content no span, do nothing
func SetAttributes(ctx context.Context, attrs map[string]interface{}) {
	s := trace.SpanFromContext(ctx)
	for k, v := range attrs {
		s.SetAttributes(makeAttribute(k, v))
	}
}

// AddEvent adds events and returns a context having span with that event
func AddEvent(ctx context.Context, s string) {
	span := trace.SpanFromContext(ctx)
	span.AddEvent(s)
}

func makeAttribute(key string, value interface{}) attribute.KeyValue {
	k := attribute.Key(key)
	switch t := value.(type) {
	case bool:
		return k.Bool(t)
	case []bool:
		return k.BoolSlice(t)
	case int:
		return k.Int(t)
	case []int:
		return k.IntSlice(t)
	case string:
		return k.String(t)
	case []string:
		return k.StringSlice(t)
	default:
		return k.String(fmt.Sprintf("%v", t))
	}
}
