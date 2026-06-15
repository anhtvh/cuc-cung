package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/dto"
	baseEntity "gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/entity/base"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/logging"
)

func (h *Handler) PayBill(c *gin.Context) {
	var (
		req     = dto.BaseRequest{}
		dataReq = baseEntity.PayBillDataRequest{}
		resp    = &dto.BaseResponse{}
		ctx     = c.Request.Context()
		logger  = logging.FromContext(ctx)
	)
	resp.DefaultResponse()
	defer func() {
		logger.WithField("[Request]", req).WithField("[Response]", resp).Infof("PayBill")
		c.JSON(http.StatusOK, resp)
	}()

	if err := h.bindAndValidate(c, &req, &dataReq); err != nil {
		resp.ReturnMessage = err.Error()
		return
	}
	dataResp := h.buz.PayBill(ctx, dataReq)
	resp.ResponseSuccess(dataResp)
}
