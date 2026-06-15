package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/constant"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/dto"
	baseEntity "gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/entity/base"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/logging"
)

func (h *Handler) GetBillInfo(c *gin.Context) {
	var (
		req     = dto.BaseRequest{}
		dataReq = baseEntity.GetBillDataRequest{}
		resp    = &dto.BaseResponse{}
		ctx     = c.Request.Context()
		logger  = logging.FromContext(ctx)
	)
	resp.DefaultResponse()
	defer func() {
		logger.WithField("[Request]", req).WithField("[Response]", resp).Infof("GetBillInfo")
		c.JSON(http.StatusOK, resp)
	}()

	if err := h.bindAndValidate(c, &req, &dataReq); err != nil {
		resp.ReturnMessage = err.Error()
		return
	}

	if dataReq.Internal == true {
		resp.ResponseSuccess(&baseEntity.GetBillDataResponse{
			BaseDataResponse: baseEntity.BaseDataResponse{
				ErrorCode: constant.ProviderInternalQuotaExceeded,
			},
		})
		return
	}
	dataResp := h.buz.GetBillInfo(ctx, dataReq)
	resp.ResponseSuccess(dataResp)
}
