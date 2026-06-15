package tracing

import (
	"context"
	"time"

	"go.opentelemetry.io/contrib/propagators/b3"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/jaeger"
	"go.opentelemetry.io/otel/exporters/stdout/stdouttrace"
	"go.opentelemetry.io/otel/sdk/resource"
	tracesdk "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.4.0"
	"go.opentelemetry.io/otel/trace"
)

// Find out more int go.opentelemetry.io/otel/semconv/v1.4.0

const (
	AttrHTTPMethod = "http.method"
)

var (
	tp          trace.TracerProvider
	serviceName string
)

func init() {
	// set new noop provider
	tp = trace.NewNoopTracerProvider()
	otel.SetTracerProvider(tp)
}

func Init(name string, expF func() (tracesdk.SpanExporter, error)) error {
	serviceName = name

	exp, err := expF()
	if err != nil {
		return err
	}
	tp = tracerProvider(serviceName, exp)

	// Register our TracerProvider as the global so any imported
	// instrumentation in the future will default to using it.
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(b3.New(b3.WithInjectEncoding(b3.B3SingleHeader), b3.WithInjectEncoding(b3.B3MultipleHeader)))
	return nil
}

func Shutdown() error {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second*5)
	defer cancel()
	switch t := tp.(type) {
	case *tracesdk.TracerProvider:
		return t.Shutdown(ctx)
	default:
		return nil
	}
}

// tracerProvider returns an OpenTelemetry TracerProvider configured to use
// the input exporter. The returned TracerProvider will also use a Resource
// configured with all the information about the application.
func tracerProvider(service string, exp tracesdk.SpanExporter) trace.TracerProvider {
	return tracesdk.NewTracerProvider(
		tracesdk.WithSampler(tracesdk.AlwaysSample()),
		tracesdk.WithBatcher(exp),
		tracesdk.WithResource(resource.NewWithAttributes(
			semconv.SchemaURL,
			semconv.ServiceNameKey.String(service),
		)),
	)
}

func STDOutExporter() func() (tracesdk.SpanExporter, error) {
	return func() (tracesdk.SpanExporter, error) {
		return stdouttrace.New(stdouttrace.WithPrettyPrint())
	}
}

func JaegerExporter(url string) func() (tracesdk.SpanExporter, error) {
	return func() (tracesdk.SpanExporter, error) {
		return jaeger.New(jaeger.WithCollectorEndpoint(jaeger.WithEndpoint(url)))
	}
}
