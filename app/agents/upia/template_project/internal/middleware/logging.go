package middleware

import (
	"bytes"
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/logging"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/tracing"
)

func RequestLogger() gin.HandlerFunc {
	type entry struct {
		RequestMethod string `json:"request_method"`
		RequestURL    string `json:"request_url"`
		ClientIP      string `json:"client_ip"`
		Status        int32  `json:"status"`
		Latency       string `json:"latency"`
	}

	return func(c *gin.Context) {
		if c.Request.Method == http.MethodGet && c.Request.URL.Path == "/metrics" {
			return
		}

		start := time.Now()
		ctx := c.Request.Context()
		ent := entry{
			ClientIP:      c.ClientIP(),
			RequestMethod: c.Request.Method,
			RequestURL:    c.Request.URL.String(),
		}
		logger := logging.FromContext(c.Request.Context())
		logger = logger.WithFields(map[string]interface{}{
			"trace_id":    getTraceID(ctx),
			"request_url": ent.RequestURL,
		})

		err := c.Request.ParseForm()
		if err != nil {
			_ = c.Error(fmt.Errorf("parse form failed: %v", err))
			c.Abort()
			return
		}
		logger.Infof("server.request: %v", c.Request.PostForm)

		c.Request = c.Request.WithContext(logging.WithLogger(c.Request.Context(), logger))
		wl := &writerLog{ResponseWriter: c.Writer, body: bytes.Buffer{}}
		c.Writer = wl
		c.Next()
		c.Writer.Status()
		logger = logging.FromContext(c.Request.Context())
		ent.Latency = time.Since(start).String()
		ent.Status = int32(wl.Status())
		logger = logger.WithField("server.response:", wl.body.String())
		logger = logger.WithField("request_metadata", ent)
		if err := c.Errors.String(); err != "" {
			logger.Errorf("finish error: %v", err)
		} else {
			logger.Infof("finish success")
		}
	}
}

type writerLog struct {
	gin.ResponseWriter
	body bytes.Buffer
}

func (w *writerLog) Write(p []byte) (n int, err error) {
	w.body.Write(p)
	return w.ResponseWriter.Write(p)
}

func getTraceID(ctx context.Context) (traceID string) {
	traceID = tracing.TraceID(ctx)
	if traceID == "" || traceID == "00000000000000000000000000000000" {
		if id, err := uuid.NewUUID(); err == nil {
			traceID = id.String()
		}
	}

	return traceID
}
