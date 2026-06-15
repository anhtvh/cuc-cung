package httpclient

import (
	"bytes"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"regexp"
	"time"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/logging"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/tracing"
)

type Client interface {
	Do(req *http.Request) (*http.Response, error)
}

type Config struct {
	proxy       func(*http.Request) (*url.URL, error)
	useTLS      bool
	enableLog   bool
	enableTrace bool
	name        string
}

type Option func(opts *Config)

func WithProxy(proxy func(*http.Request) (*url.URL, error)) Option {
	return func(opts *Config) {
		opts.proxy = proxy
	}
}

func EnableTLS(useTLS bool) Option {
	return func(opts *Config) {
		opts.useTLS = useTLS
	}
}

func EnableLog() Option {
	return func(opts *Config) {
		opts.enableLog = true
	}
}

func EnableTrace() Option {
	return func(opts *Config) {
		opts.enableTrace = true
	}
}

func WithName(name string) Option {
	return func(opts *Config) {
		opts.name = name
	}
}

func Default(name string, opts ...Option) Client {
	opts = append(opts, WithName(name), EnableLog(), EnableTrace())
	return New(opts...)
}

func New(opts ...Option) Client {
	cfg := Config{
		proxy: http.ProxyFromEnvironment,
	}

	for _, o := range opts {
		o(&cfg)
	}

	var c Client = &http.Client{
		Transport: &http.Transport{
			Proxy: cfg.proxy,
			DialContext: (&net.Dialer{
				Timeout:   30 * time.Second,
				KeepAlive: 30 * time.Second,
			}).DialContext,
			MaxIdleConns:          100,
			IdleConnTimeout:       90 * time.Second,
			TLSHandshakeTimeout:   10 * time.Second,
			ExpectContinueTimeout: 1 * time.Second,
			TLSClientConfig: &tls.Config{
				InsecureSkipVerify: cfg.useTLS,
			},
		},
		Timeout: 120 * time.Second,
	}

	if cfg.enableTrace {
		c = newSpanClient(c, cfg.name)
	}

	if cfg.enableLog {
		c = newLogClient(c, cfg.name)
	}

	return c
}

type logClient struct {
	c    Client
	name string
}

func newLogClient(c Client, name string) Client {
	return &logClient{c: c, name: name}
}

func (c *logClient) Do(req *http.Request) (*http.Response, error) {
	logger := logging.FromContext(req.Context())
	if reqBody, err := httputil.DumpRequest(req, true); err == nil {
		reqBodyStr := string(reqBody)
		rePassword := regexp.MustCompile(`("password"\s*:\s*")[^"]*(")`)
		reqBodyStr = rePassword.ReplaceAllString(reqBodyStr, `${1}xxx${2}`)
		logger.Infof("%s.client.request: %s", c.name, reqBodyStr)
	} else {
		return nil, fmt.Errorf("dump request body: %v", err)
	}

	start := time.Now()
	res, err := c.c.Do(req)
	if err != nil {
		return res, err
	}

	logger = logger.
		WithField("client.latency", time.Since(start).String()).
		WithField("client.status", res.StatusCode)

	if resBody, err := httputil.DumpResponse(res, true); err == nil {
		logger.Infof("%s.client.response: %s", c.name, string(resBody))
	} else {
		return res, fmt.Errorf("dump response body: %v", err)
	}

	return res, nil
}

type traceClient struct {
	c    Client
	name string
}

func newSpanClient(c Client, prefix string) Client {
	return &traceClient{c: c, name: prefix}
}

func (c *traceClient) Do(req *http.Request) (*http.Response, error) {
	ctx := tracing.StartSpan(req.Context(), fmt.Sprintf("%s: %s", c.name, req.URL))
	defer tracing.EndSpan(ctx)

	return c.c.Do(req)
}

// FakeResponse return a fake *http.Response
func FakeResponse(code int, body []byte) *http.Response {
	return &http.Response{
		Status:        http.StatusText(code),
		StatusCode:    code,
		Body:          io.NopCloser(bytes.NewReader(body)),
		ContentLength: int64(len(body)),
		Header:        make(http.Header),
	}
}
