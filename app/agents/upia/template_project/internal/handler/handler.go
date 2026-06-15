package handler

import (
	"errors"
	"fmt"

	"github.com/gin-gonic/gin"
	validatorV10 "github.com/go-playground/validator/v10"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/business/manager/common"
)

type (
	ServerRequest interface {
		DeserializeData(out interface{}) error
		ValidateSig(key string) bool
		GetClientID() string
	}
)

func NewHandler(clientMap map[string]string, buz common.Service) *Handler {
	return &Handler{
		buz:       buz,
		clientMap: clientMap,
		validator: validatorV10.New(),
	}
}

type Handler struct {
	buz       common.Service
	clientMap map[string]string
	validator *validatorV10.Validate
}

func (h *Handler) bindAndValidate(c *gin.Context, req ServerRequest, pReqData interface{}) error {
	if err := c.ShouldBind(req); err != nil {
		return fmt.Errorf("bind error: %w", err)
	}

	if len(h.clientMap) != 0 {
		key, ok := h.clientMap[req.GetClientID()]
		if !ok {
			return errors.New(fmt.Sprintf("client with clientID = %v not found", req.GetClientID()))
		}

		if !req.ValidateSig(key) {
			return errors.New("sig not match")
		}
	}

	if err := req.DeserializeData(pReqData); err != nil {
		return fmt.Errorf("unmarshal data request [%v] error: %w", pReqData, err)
	}

	if err := h.validator.Struct(pReqData); err != nil {
		return fmt.Errorf("validate data request [%v] error: %w", pReqData, err)
	}

	return nil
}

func (h *Handler) SetupRouter(e *gin.Engine) {
	v1 := e.Group("/v1")
	{
		v1.POST("/bill/info", h.GetBillInfo)
		v1.POST("/bill/pay", h.PayBill)
		v1.POST("/bill/check", h.CheckTransaction)
		v1.POST("/bill/re-deliver", h.ReDeliver)
	}
}
