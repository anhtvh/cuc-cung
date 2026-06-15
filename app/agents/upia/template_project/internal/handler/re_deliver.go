package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/dto"
	baseEntity "gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/entity/base"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/logging"
)

func (h *Handler) ReDeliver(c *gin.Context) {
	var (
		ctx     = c.Request.Context()
		logger  = logging.FromContext(ctx)
		req     = dto.BaseRequest{}
		resp    = &dto.BaseResponse{}
		dataReq = baseEntity.PayBillDataRequest{}
	)
	defer func() {
		logger.WithField("[Request]", req).WithField("[Response]", resp).Infof("ReDeliver")
		c.JSON(http.StatusOK, resp)
	}()
	resp.DefaultResponse()
	if err := h.bindAndValidate(c, &req, &dataReq); err != nil {
		resp.ReturnMessage = err.Error()
		return
	}
	//buz := h.buzCommonStrategyFactory.GetBuzCommonStrategy(constant.ServiceID(dataReq.Bills[0].ServiceID))
	//if buz == nil {
	//	resp.ReturnMessage = fmt.Sprintf("service_id %v not supported", dataReq.Bills[0].ServiceID)
	//	return
	//}
	dataResp := h.buz.ReDeliver(ctx, dataReq)
	resp.ResponseSuccess(dataResp)
}
