package metrics

import (
	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

const (
	Path = "/metrics"
)

type DefaultLabels struct {
	// ServiceName composed by domain-project
	ServiceName string
}

func Handler() gin.HandlerFunc {
	return gin.WrapH(promhttp.Handler())
}
