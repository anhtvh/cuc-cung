package metrics

import (
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

type Egress interface {
	Observe(method, code, errCode, detailErrorCode string, start time.Time)
}

func NewEgress(service string, labels DefaultLabels) Egress {
	return &egress{
		labels: labels,
		reqCnt: promauto.NewCounterVec(prometheus.CounterOpts{
			Namespace: service,
			Name:      "egress_requests_total",
			Help:      "How many HTTP requests processed, partitioned by return code and HTTP method.",
		}, []string{"application", "code", "error", "detail_error", "method"}),

		reqDur: promauto.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: service,
			Name:      "egress_request_duration_seconds",
			Help:      "The HTTP request latencies in seconds.",
			Buckets:   []float64{.01, .02, .03, .05, .1, .2, .3, .5, 1, 2, 3, 5, 10, 20},
		}, []string{"application", "code", "error", "detail_error", "method"}),
	}
}

type egress struct {
	labels DefaultLabels

	reqCnt *prometheus.CounterVec
	reqDur *prometheus.HistogramVec
}

func (o *egress) Observe(method, code, errCode string, detailErrorCode string, start time.Time) {
	o.reqCnt.WithLabelValues(o.labels.ServiceName, code, errCode, detailErrorCode, method).Inc()
	o.reqDur.WithLabelValues(o.labels.ServiceName, code, errCode, detailErrorCode, method).Observe(time.Since(start).Seconds())
}

func NewNoopEgress() Egress {
	return &noopEgress{}
}

// noopEgress using for test, not perform anything
type noopEgress struct {
}

func (m *noopEgress) Observe(_, _, _, _ string, _ time.Time) {}
