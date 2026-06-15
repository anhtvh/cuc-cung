# zalopay Provider Pattern Reference

This file contains all zalopay-internal constants, interfaces, and patterns that the agent
must follow when generating code. It is embedded here so the agent is fully self-contained
and does not depend on any external knowledge source.

---

## About the template project (`provider-imedia`)

The template repo serves two purposes only:

1. **Infrastructure scaffold** — copy as-is, do not modify:
   `internal/httpclient/`, `internal/logging/`, `internal/metrics/` (framework only),
   `internal/tracing/`, `internal/caching/`, `internal/middleware/`, `internal/handler/`,
   `internal/utils/`, `internal/entity/base/`, `internal/business/base.go`,
   `internal/business/manager/interface.go`, `internal/business/manager/common/service.go`

   `internal/middleware/` must provide — verify these are present before copying:
   - Ingress RED metrics: emit `http_requests_total` and `http_request_duration_seconds` with labels `{method, route, http_status, return_code}`. Route label uses `c.FullPath()` — never the resolved path with IDs.
   - Trace context extraction: read W3C `traceparent` header to continue an upstream trace (so ingress span links to the caller's trace).
   - Trace-log injection: bind `trace_id` + `span_id` into the request context logger.

   `internal/utils/` must contain a `Truncate(s string, n int) string` helper.
   If absent, add it — it is used in every provider method for provider return message handling.

2. **Flow reference** — read to understand how GetBill/PayBill/CheckPay chain together
   in `common/service.go`. Do not copy implementation.

**The template is NOT a Go coding standard.** Its implementation files (`provider/client.go`,
`entity/provider/`, `business/manager/*/service.go`) were built for delivery speed, not
code quality. Do NOT copy their style, structure, or patterns — write all implementation
files from scratch using `agent/templates/` and the standards below.

Phase 2 deletes all implementation files from the cloned template before Phase 3 begins,
so there is nothing left to "modify" — only fresh files to write.

---

## Go coding standards for generated files

### Error handling
- Wrap with context: `fmt.Errorf("get bill: %w", err)` — never swallow silently
- Return early on error; avoid deeply nested if/else
- Only validate at system boundaries (user input, HTTP response); trust internal contracts

### Naming
- Packages: short lowercase nouns — `provider`, `constant`, `electricity`
- Interfaces: noun or noun-phrase — `Provider`, `ConverterStrategy`
- Methods: verb-first — `GetBill`, `ConvertBillEntity`, `getAccessToken`
- Acronyms stay all-caps — `HTTPClient`, `APIKey`, `IDGiaoDich`, `URL`
- Unexported names for internal state — `accessToken`, `tokenExpiry`, `mu`

### Struct design
- Exported fields for JSON/config serialization; unexported for internal-only state
- Document what a mutex protects with a comment directly above the field:
  ```go
  // mu protects accessToken and tokenExpiry
  mu          sync.Mutex
  accessToken string
  tokenExpiry time.Time
  ```

### Context
- Always first parameter (`ctx context.Context`); never stored in a struct
- Propagate to all I/O calls — HTTP, cache, tracing spans

### Comments
- Only when the WHY is non-obvious (hidden constraint, non-obvious invariant)
- No docstrings that restate the function name
- No inline comments explaining what the code does

### DTO vs Entity separation

Two distinct layers — never mix them:

| Layer | Package | Purpose | Visibility |
|---|---|---|---|
| **DTO** | `internal/provider/` (dto.go) | Raw HTTP JSON to/from partner | Private to `provider` package |
| **Entity** | `internal/entity/provider/` | Normalized business types; `FinalStatus` already set | Used across business layer |

Rules:
- DTO fields: exact partner JSON keys as json tags. No business logic.
- Entity fields: Go-idiomatic names. `FinalStatus`, `Message`, `OriginalStatus`, `DescriptionStatus` always `json:"-"`.
- The provider `client.go` is the **only** place that converts DTO → Entity. No code outside `provider/` ever sees a DTO type.
- `internal/entity/base/` types flow from business layer upward to handler — `provider/entity` types never reach the handler.

### Testing
- Table-driven: `tests := []struct{ name string; ... }{ {...}, {...} }`
- Name each case to describe the scenario: `"customer not found"`, `"token expired"`
- Mock only at interface boundaries (`Provider`, `httpclient.IHttpClient`)
- Test behaviour, not implementation — assert outputs, not internal state

---

## Internal error code constants (`internal/constant/core.go`)

These are **fixed zalopay platform values** — do not change them. Copy verbatim.

```go
const (
    Exception      = 0
    ProviderSuccess = 1

    ProviderUnavailable    = -550
    ProviderTimeout        = -551
    ProviderBillEmpty      = -553
    ProviderCustomerCodeNotExist = -554
    ProviderAPIFail        = -556
    ProviderReturnFail     = -559
    ProviderReachLimitation = -562
    ProviderMaintenance    = -593
    ProviderBillLocked     = -594
    ProviderErrorCodeNotDefined = -599
)

const (
    DeliverSuccess      = 1
    DeliverProcessing   = 3
    WaitGetStatusDeliver = 7
    DeliverManualCheck  = -400   // unknown outcome — manual reconciliation
    DeliverFail         = -401   // definitive failure — triggers auto-refund
)

const (
    PaymentRuleAll             = "1"  // user must pay all bills
    PaymentRuleOldestBill      = "2"  // user pays oldest bill first
    PaymentRuleAnyBill         = "3"  // user picks any bill
    PaymentRuleInputAmount     = "5"  // user inputs custom amount
    PaymentRuleContiguousBills = "6"  // user pays contiguous bills from first
)
```

---

## Error mapping rule

**Query endpoints (GetBill, CheckBalance):**
- Partner success code → `ProviderSuccess`
- Anything else → use the most specific constant that fits, or `ProviderErrorCodeNotDefined` as default

**Payment endpoints (PayBill, CheckPay):**
- Partner success code → `DeliverSuccess`
- **Any outcome that is not confirmed success → `DeliverManualCheck` (-400)**
- `DeliverFail` (-401) is **never** returned by `MapPaymentStatusCode` — it is a platform constant reserved for other internal use. Do not add it as a case in payment status mapping.

The exhaustive switch pattern:
```go
func MapPaymentStatusCode(code string) int {
    switch code {
    case ProviderCodeSuccess:
        return DeliverSuccess
    case ProviderCode...:      // add cases for each known code
        return DeliverManualCheck
    default:
        return DeliverManualCheck  // always DeliverManualCheck for unknown
    }
}
```

---

## Provider interface (`internal/provider/client.go`)

Every partner adapter must implement this interface:

```go
type Provider interface {
    GetBill(ctx context.Context, req *providerEntity.GetBillDataRequest) (*providerEntity.GetBillDataResponse, error)
    PayBill(ctx context.Context, req *providerEntity.PayBillDataRequest) (*providerEntity.PayBillDataResponse, error)
    CheckPay(ctx context.Context, req *providerEntity.CheckPayDataRequest) (*providerEntity.CheckPayDataResponse, error)
    CheckBalance(ctx context.Context) (*providerEntity.BalanceResponse, error) // optional
}
```

Each method must:
1. Start a tracing span: `tracing.StartSpan(ctx, "provider.client.{method_name}")`
2. Defer `collector.Observe(method, statusCode, errorCode, detailErrorCode, start)` and `tracing.EndSpan`
3. Build auth signature / credentials per `schema.auth`
4. Call `sendRequest` → `parseResponse`
5. Check the partner status field; on non-success return an error

---

## ConverterStrategy interface (`internal/business/manager/interface.go`)

```go
type ConverterStrategy interface {
    GetPaymentRule() string
    ConvertBillEntity(serviceID string, providerID string, providerResp *providerEntity.GetBillDataResponse) []baseEntity.Bill
    GetContractType(srvID string) string
}
```

One implementation per service type (e.g., electricity, water, consumer-finance).

---

## Idempotency pattern (`internal/business/manager/common/service.go`)

`SetNXTransID` must be called **before** the PayBill provider call:

```go
func (s *service) PayBill(ctx context.Context, req baseEntity.PayBillDataRequest) *baseEntity.PayBillDataResponse {
    isDuplicated := s.cacheSrv.SetNXTransID(ctx, "deliver", req.TransactionID, 10*24*time.Hour)
    if !isDuplicated {
        return &baseEntity.PayBillDataResponse{
            BaseDataResponse: baseEntity.BaseDataResponse{
                ErrorCode: constant.DeliverManualCheck,
                ProviderReturnMessage: "duplicate transaction detected",
            },
        }
    }
    return s.processDeliver(ctx, req)
}
```

---

## Metrics pattern (`internal/metrics/`)

Egress metrics are tracked per method with error labels. The `Observe` call in each provider method:

```go
defer func(start time.Time) {
    p.collector.Observe("provider.client.get_bill", statusCode, errorCode, detailErrorCode, start)
    tracing.EndSpan(spanCtx)
}(time.Now())
```

`statusCode` = HTTP status code (as string), `errorCode` = partner status code, `detailErrorCode` = inner status.

---

## Observability Standards

### E2E Tracing — Jaeger via OTLP

Every service uses OpenTelemetry SDK with OTLP exporter (Jaeger). Trace context is propagated via **W3C TraceContext** headers (`traceparent`, `tracestate`) on all outbound HTTP calls.

The `internal/tracing/` package handles SDK init and span management — do not call OTLP directly in business or provider code.

Span naming convention:
- Ingress spans: `http.server.{gin_route}` (e.g. `http.server./v1/bill/:serviceId`)
- Business spans: `business.manager.{method}` (e.g. `business.manager.get_bill`)
- Egress spans: `provider.client.{method}` (e.g. `provider.client.get_bill`)

### Span Attributes (OTel Semantic Conventions)

**Ingress** (set by `internal/middleware/`):
```
http.method        = "POST"
http.route         = c.FullPath()   // Gin route pattern, NOT the resolved path
http.status_code   = response status
return_code        = zalopay internal code (int)
```

**Egress** (set by every provider method):
```
http.method           = "POST"
http.url              = endpoint path only — never full URL with credentials
http.status_code      = partner HTTP status (int)
partner.return_code   = partner raw status field (string)
partner.return_message = partner message, truncated to 100 chars (string)
return_code           = zalopay mapped code: MapQueryStatusCode / MapPaymentStatusCode result (int)
```

Setting span attributes example:
```go
spanCtx := tracing.StartSpan(ctx, "provider.client.get_bill")
tracing.SetAttribute(spanCtx, "http.url", endpointGetBill)
// ... after HTTP call:
tracing.SetAttribute(spanCtx, "http.status_code", httpStatus)
tracing.SetAttribute(spanCtx, "partner.return_code", dto.BaseResponse.StatusCode)
tracing.SetAttribute(spanCtx, "partner.return_message", truncate(dto.BaseResponse.Description, 100))
tracing.SetAttribute(spanCtx, "return_code", mappedCode)
```

### Trace-Log Correlation

Every log line **must** include `trace_id` and `span_id` extracted from the current span.
The `internal/logging/` package injects these automatically from context — always use `logging.FromContext(ctx)`, never create a bare logger.

```go
log := logging.FromContext(ctx)  // has trace_id, span_id bound
log.WithField("customer_code", req.CustomerCode).Info("get bill request")
```

### RED Metrics — Ingress (`internal/middleware/`)

Labels for all HTTP handler metrics:
```
method      = HTTP method ("POST", "GET")
route       = Gin full path pattern (c.FullPath()) — no dynamic segments in label value
http_status = HTTP status code ("200", "400", "500")
return_code = zalopay internal code ("-550", "1", ...)
```

Metric names (per RED):
- `http_requests_total{method, route, http_status, return_code}` — Rate / Error
- `http_request_duration_seconds{method, route}` — Duration

### RED Metrics — Egress (`internal/metrics/`)

Labels for all provider call metrics:
```
partner       = partner name constant (e.g. "evnhcm")
endpoint      = function slug ("get_bill", "pay_bill", "check_pay")
http_status   = partner HTTP status code ("200", "500", "0" for timeout)
provider_code = partner raw return code/status field — bounded set, safe as label
return_code   = zalopay mapped code (output of MapQueryStatusCode / MapPaymentStatusCode)
```

Metric names:
- `provider_requests_total{partner, endpoint, http_status, provider_code, return_code}` — Rate / Error
- `provider_request_duration_seconds{partner, endpoint}` — Duration

### Provider Return Message Handling

**Do NOT use provider return message as a Prometheus label** — free-text with dynamic content causes unbounded cardinality and can OOM Prometheus.

Instead:
1. **Truncate** to 100 characters: `msg = truncate(rawMsg, 100)`
2. **Log** as a structured field: `log.WithField("provider_message", msg).Warn(...)`
3. **Set as span attribute**: `tracing.SetAttribute(spanCtx, "partner.return_message", msg)`

Helper to use in every provider method:
```go
func truncate(s string, n int) string {
    if len(s) <= n {
        return s
    }
    return s[:n]
}
```

This helper lives in `internal/utils/` — do not rewrite it per-file.

---

## Base entity types (`internal/entity/base/base.go`)

Key types that every `ConvertBillEntity` implementation must populate:

```go
type Bill struct {
    BillID       string
    Month        string   // "MM"
    Year         string   // "YYYY"
    TotalAmount  int64    // in VND
    PaymentFee   int64
    DueDate      string
    ServiceID    string
    CustomerID   string
    CustomerCode string
    CustomerName string
    ExInfo       string   // JSON-encoded ExtInfo
}

type ExtInfo struct {
    CustomerCode  string `json:"customercode"`
    CustomerName  string `json:"customername"`
    TotalDebt     int64  `json:"totaldebt"`
    ReferenceCode string `json:"referencecode"`
    ServiceCode   string `json:"serviceid"`
}

type ExtAmount struct {
    MinInput int32  `json:"mininput"`
    MaxInput int64  `json:"maxinput"`   // -1 = no limit
    Default  int64  `json:"default"`
}
```

---

## Logging rules

- Use structured logging via `logging.FromContext(ctx)`
- Log fields: use `WithField(key, value)` for structured data
- **Never log PII**: no customer name, phone, ID card number, card number
- Amount values are safe to log; card numbers log last 4 digits only

---

## Config struct pattern (`internal/config/config.go`)

```go
type Configuration struct {
    App      App
    Proxy    Proxy
    Provider Provider
    Tracing  Tracing
    Cache    Cache
}

type Provider struct {
    Endpoint      string  `mapstructure:"endpoint"`
    // Add only what the partner actually needs:
    // Username, Password, APIKey, PrivateKey, PublicKey, MinAmount, SkipVerifySSL
}
```

---

## MR description template

When creating the MR in Phase 4, use this exact structure:

```markdown
## Purpose & Motivation

Implement {partner_name} bill payment adapter for zalopay.

Partner  : {partner_name}
Services : {list of service IDs and their descriptions}
Auth     : {auth type}

## Key Changes

- `internal/constant/provider.go`: {n} error codes + query/payment status mapping
- `internal/entity/provider/`: request/response structs for {n} endpoints
- `internal/provider/client.go`: HTTP client with {auth_type} authentication
- `internal/business/manager/{type}/service.go`: converter strategy for {service types}
- Test suite: table-driven unit tests, mock HTTP client, error mapping coverage

## Verification & Testing

- `go build ./...`: ✅ clean
- `go test ./... -race`: {n}/{total} passed, coverage {n}%
- Integration tests: {passed | skipped — no sandbox URL}

See `docs/test-results.md` for full report.

## Risk Assessment

**Risk level:** LOW

- New adapter — no changes to existing providers or shared infrastructure
- Error mapping default: DeliverManualCheck (-400)
- Idempotency: SetNXTransID called before every PayBill
- Rollback: revert this MR — no database migrations, no shared state changes

## Open questions

See `docs/open-questions.md`.

## Ready-to-merge checklist

- [ ] `go build ./...` passes
- [ ] `go test ./... -race` passes
- [ ] All partner error codes have explicit mapping cases
- [ ] No secrets hardcoded
- [ ] No PII logged
- [ ] `docs/` committed with this MR
```
