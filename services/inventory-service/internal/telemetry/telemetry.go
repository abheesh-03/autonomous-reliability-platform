// Package telemetry sets up the OpenTelemetry SDK (traces + metrics)
// for inventory-service: an OTLP/HTTP trace exporter feeding a
// BatchSpanProcessor, an OTLP/HTTP metric exporter feeding a
// PeriodicReader, a resource built from the environment, and a global
// W3C tracecontext+baggage propagator. It is only ever called from the
// normal server startup path (cmd/inventory-service/main.go's run()),
// never from the "healthcheck" subcommand.
package telemetry

import (
	"context"
	"errors"
	"fmt"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// Shutdown flushes and closes every telemetry provider that was
// started. It is safe to call exactly once, during graceful shutdown.
type Shutdown func(context.Context) error

// Setup builds the resource, trace pipeline, and metric pipeline, and
// installs them (plus a composite TraceContext+Baggage propagator) as
// the process-wide OpenTelemetry defaults. Resource attributes are
// read from OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES via
// resource.WithFromEnv() — the service name is never hard-coded here,
// since Docker Compose already provides it. If any step fails, Setup
// returns a non-nil error so the caller can fail startup clearly
// rather than run with partially configured telemetry — and any
// providers already created before the failing step are shut down
// first, so a partial setup never leaks a provider/exporter.
func Setup(ctx context.Context) (Shutdown, error) {
	res, err := resource.New(ctx,
		resource.WithFromEnv(),
		resource.WithTelemetrySDK(),
		resource.WithHost(),
		resource.WithOS(),
		resource.WithProcess(),
	)
	if err != nil {
		return nil, fmt.Errorf("telemetry: build resource: %w", err)
	}

	traceExporter, err := otlptracehttp.New(ctx)
	if err != nil {
		return nil, fmt.Errorf("telemetry: create OTLP trace exporter: %w", err)
	}

	// WithBatcher wraps the exporter in a BatchSpanProcessor with no
	// explicit timing options overridden, so the SDK's own env-aware
	// defaults (OTEL_BSP_SCHEDULE_DELAY, etc.) apply.
	tracerProvider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(traceExporter),
		sdktrace.WithResource(res),
	)

	metricExporter, err := otlpmetrichttp.New(ctx)
	if err != nil {
		// tracerProvider was already created and may own a
		// BatchSpanProcessor/exporter lifecycle; shut it down rather
		// than leaking it before returning the original setup error.
		setupErr := fmt.Errorf("telemetry: create OTLP metric exporter: %w", err)
		if shutdownErr := tracerProvider.Shutdown(ctx); shutdownErr != nil {
			return nil, errors.Join(setupErr, fmt.Errorf("telemetry: shut down tracer provider after failed setup: %w", shutdownErr))
		}
		return nil, setupErr
	}

	// NewPeriodicReader with no WithInterval override similarly honors
	// OTEL_METRIC_EXPORT_INTERVAL via the SDK's own env-aware default.
	meterProvider := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(metricExporter)),
		sdkmetric.WithResource(res),
	)

	otel.SetTracerProvider(tracerProvider)
	otel.SetMeterProvider(meterProvider)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	shutdown := func(shutdownCtx context.Context) error {
		var errs error
		if err := tracerProvider.Shutdown(shutdownCtx); err != nil {
			errs = errors.Join(errs, fmt.Errorf("telemetry: shut down tracer provider: %w", err))
		}
		if err := meterProvider.Shutdown(shutdownCtx); err != nil {
			errs = errors.Join(errs, fmt.Errorf("telemetry: shut down meter provider: %w", err))
		}
		return errs
	}

	return shutdown, nil
}
