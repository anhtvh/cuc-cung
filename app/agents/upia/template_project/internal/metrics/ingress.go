package metrics

import (
	"bytes"
	"encoding/json"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var noOp = func(url string) string {
	// do nothing
	return url
}

type Ingress struct {
	labels DefaultLabels

	NormalizeURL func(url string) string

	reqCnt *prometheus.CounterVec
	reqDur *prometheus.HistogramVec
}

func NewIngress(service string, labels DefaultLabels) Ingress {
	return Ingress{
		labels:       labels,
		NormalizeURL: noOp,

		reqCnt: promauto.NewCounterVec(prometheus.CounterOpts{
			Namespace: service,
			Name:      "requests_total",
			Help:      "How many HTTP requests processed, partitioned by return code and HTTP method.",
		}, []string{"application", "status", "code", "errorCode", "method", "handler", "host", "url"}),

		reqDur: promauto.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: service,
			Name:      "request_duration_seconds",
			Help:      "The HTTP request latencies in seconds.",
			Buckets:   []float64{.01, .02, .03, .05, .1, .2, .3, .5, 1, 2, 3, 5, 10, 20},
		}, []string{"application", "status", "code", "errorCode", "method", "url"}),
	}
}

func (i *Ingress) GinMiddleWare() gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.URL.Path == Path {
			c.Next()
			return
		}

		start := time.Now()
		// This is workaround for catching response body
		blw := &bodyLogWriter{body: bytes.NewBufferString(""), ResponseWriter: c.Writer}
		c.Writer = blw
		c.Next()

		// This is workaround for catching response body
		var (
			code      string
			errorCode string
		)
		if blw.body.Len() != 0 {
			var (
				resp struct {
					ReturnCode            int    `json:"returncode"`
					Message               string `json:"message"`
					ProviderReturnMessage string `json:"providerreturnmessage"`
					ProviderReturnCode    int    `json:"providerreturncode"`
					Data                  string `json:"data"`
				}
				dataResp struct {
					ErrorCode int `json:"errorcode"`
				}
			)
			if err := json.Unmarshal(blw.body.Bytes(), &resp); err == nil {
				code = strconv.Itoa(resp.ReturnCode)
				if resp.Data != "" {
					if err := json.Unmarshal([]byte(resp.Data), &dataResp); err == nil {
						errorCode = strconv.Itoa(dataResp.ErrorCode)
					}
				}
			}
		}

		status := strconv.Itoa(c.Writer.Status())
		url := i.NormalizeURL(c.Request.URL.Path)
		i.reqDur.WithLabelValues(i.labels.ServiceName, status, code, errorCode, c.Request.Method, url).Observe(time.Since(start).Seconds())
		i.reqCnt.WithLabelValues(i.labels.ServiceName, status, code, errorCode, c.Request.Method, c.HandlerName(), c.Request.Host, url).Inc()
	}
}
