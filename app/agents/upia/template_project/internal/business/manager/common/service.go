package common

import (
	"context"
	"fmt"
	"time"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/business"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/caching"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/constant"
	baseEntity "gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/entity/base"
	providerEntity "gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/entity/provider"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/logging"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/provider"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/tracing"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/utils/jsonutils"
)

//go:generate mockgen -destination=mocks/service_mock.go -package=mocks -source=service.go
type Service interface {
	GetBillInfo(ctx context.Context, req baseEntity.GetBillDataRequest) *baseEntity.GetBillDataResponse
	PayBill(ctx context.Context, req baseEntity.PayBillDataRequest) *baseEntity.PayBillDataResponse
	ReDeliver(ctx context.Context, req baseEntity.PayBillDataRequest) *baseEntity.PayBillDataResponse
	CheckTransaction(ctx context.Context, req baseEntity.CheckTransactionDataRequest) *baseEntity.CheckTransactionDataResponse
}
type service struct {
	provider         map[constant.ServiceID]provider.Provider
	cacheSrv         caching.Service
	converterService business.ConverterStrategyFactory
}

func (s *service) GetBillInfo(ctx context.Context, req baseEntity.GetBillDataRequest) *baseEntity.GetBillDataResponse {
	spanCtx := tracing.StartSpan(ctx, "business.consumer_finance.get_bill_info")
	defer tracing.EndSpan(spanCtx)
	var (
		resp = &baseEntity.GetBillDataResponse{
			BaseDataResponse: baseEntity.DefaultBaseDataResponse(),
		}
	)

	getBillReq := &providerEntity.GetBillDataRequest{
		RequestID:    tracing.TraceID(ctx),
		ServiceCode:  req.ProviderID,
		CustomerCode: req.CustomerID,
		PhoneNumber:  req.PhoneNumber,
	}

	pro, ok := s.provider[constant.ServiceID(req.ServiceID)]
	if !ok {
		logErrorService(ctx, req.ServiceID)
		return resp
	}

	converterService := s.converterService.GetConverterStrategy(constant.ServiceID(req.ServiceID))
	if converterService == nil {
		logErrorService(ctx, req.ServiceID)
		return resp
	}

	getBillResp, err := pro.GetBill(spanCtx, getBillReq)
	if err != nil {
		return resp
	}

	errCode := constant.MapQueryStatusCode(getBillResp.FinalStatus)
	resp = &baseEntity.GetBillDataResponse{
		BaseDataResponse: baseEntity.BaseDataResponse{
			ErrorCode:          errCode,
			ProviderReturnCode: getBillResp.FinalStatus,
		},
		ContractData: baseEntity.Contract{
			Code: req.CustomerID,
		},
	}
	if errCode != constant.ProviderSuccess {
		return resp
	}

	resp.Bills = converterService.ConvertBillEntity(req.ServiceID, req.ProviderID, getBillResp)
	resp.PaymentRule = converterService.GetPaymentRule()
	resp.ContractData = baseEntity.Contract{
		Code:    getBillResp.BillingCode,
		Name:    getBillResp.CustomerName,
		Address: getBillResp.CustomerAddress,
		Type:    converterService.GetContractType(req.ServiceID),
	}

	return resp
}

func (s *service) CheckTransaction(ctx context.Context, req baseEntity.CheckTransactionDataRequest) *baseEntity.CheckTransactionDataResponse {
	spanCtx := tracing.StartSpan(ctx, "business.common.check-transaction")
	defer tracing.EndSpan(spanCtx)
	var (
		logger = logging.FromContext(ctx)
		resp   = &baseEntity.CheckTransactionDataResponse{
			BaseDataResponse: baseEntity.BaseDataResponse{
				ErrorCode: constant.DeliverManualCheck,
			},
		}
	)

	var transactionExtInfo baseEntity.CheckTransactionExInfo
	err := jsonutils.FromJsonString(req.ExInfo, &transactionExtInfo)
	if err != nil {
		logger.Errorf("err %s", err.Error())
		return resp
	}

	pro, ok := s.provider[constant.ServiceID(transactionExtInfo.AppServiceID)]
	if !ok {
		resp.BaseDataResponse.ProviderReturnMessage = fmt.Sprintf("service_id %v not supported", constant.ServiceID(transactionExtInfo.AppServiceID))
		logErrorService(ctx, transactionExtInfo.AppServiceID)
		return resp
	}

	checkTransDataReq := &providerEntity.CheckPayDataRequest{
		RequestID:     tracing.TraceID(spanCtx),
		TransactionID: req.ProviderTransactionID,
	}

	checkTransDataResp, err := pro.CheckPay(spanCtx, checkTransDataReq)
	if err != nil {
		resp.ProviderReturnMessage = err.Error()
		return resp
	}

	errCode := constant.MapQueryStatusCode(checkTransDataResp.OriginalStatus)
	if errCode != constant.DeliverSuccess {
		resp.ErrorCode = constant.DeliverManualCheck
		resp.ProviderReturnCode = checkTransDataResp.OriginalStatus
		resp.ProviderReturnMessage = checkTransDataResp.DescriptionStatus
		resp.ProviderData = jsonutils.ToJSONString(checkTransDataResp)
		return resp
	}

	resp.ErrorCode = constant.DeliverSuccess
	resp.ProviderReturnCode = checkTransDataResp.OriginalStatus
	resp.ProviderReturnMessage = checkTransDataResp.DescriptionStatus
	resp.ProviderData = jsonutils.ToJSONString(checkTransDataResp)
	return resp
}

func (s *service) PayBill(ctx context.Context, req baseEntity.PayBillDataRequest) *baseEntity.PayBillDataResponse {
	spanCtx := tracing.StartSpan(ctx, "business.common.deliver")
	defer tracing.EndSpan(spanCtx)
	isDuplicated := s.cacheSrv.SetNXTransID(ctx, "deliver", req.TransactionID, 10*24*time.Hour)
	if !isDuplicated {
		return &baseEntity.PayBillDataResponse{
			BaseDataResponse: baseEntity.BaseDataResponse{
				ErrorCode:             constant.DeliverManualCheck,
				ProviderReturnMessage: fmt.Sprintf("deliver failed with check duplicated trans_id result: %v", isDuplicated),
			},
			ProviderTransID: req.TransactionID,
		}
	}
	return s.processDeliver(spanCtx, req)
}

func (s *service) ReDeliver(ctx context.Context, req baseEntity.PayBillDataRequest) *baseEntity.PayBillDataResponse {
	spanCtx := tracing.StartSpan(ctx, "business.common.re-deliver")
	defer tracing.EndSpan(spanCtx)
	isDuplicated := s.cacheSrv.SetNXTransID(ctx, "re-deliver", req.TransactionID, 10*24*time.Hour)
	if !isDuplicated {
		return &baseEntity.PayBillDataResponse{
			BaseDataResponse: baseEntity.BaseDataResponse{
				ErrorCode:             constant.DeliverManualCheck,
				ProviderReturnMessage: fmt.Sprintf("re-deliver failed with check duplicated trans_id result: %v", isDuplicated),
			},
			ProviderTransID: req.TransactionID,
		}
	}
	return s.processDeliver(spanCtx, req)
}

func (s *service) processDeliver(ctx context.Context, req baseEntity.PayBillDataRequest) *baseEntity.PayBillDataResponse {
	var (
		resp = &baseEntity.PayBillDataResponse{
			BaseDataResponse: baseEntity.BaseDataResponse{
				ErrorCode: constant.DeliverManualCheck,
			},
			ProviderTransID: req.TransactionID,
		}
	)
	pro, ok := s.provider[constant.ServiceID(req.Bills[0].ServiceID)]
	if !ok {
		logErrorService(ctx, req.Bills[0].ServiceID)
		resp.BaseDataResponse.ProviderReturnMessage = fmt.Sprintf("service_id %v not supported", constant.ServiceID(req.Bills[0].ServiceID))

		return resp
	}

	var billExtInfo baseEntity.ExtInfo
	err := jsonutils.FromJsonString(req.Bills[0].ExInfo, &billExtInfo)
	if err != nil {
		resp.ProviderReturnMessage = err.Error()
		return resp
	}

	totalAmount := int64(0)
	for _, bill := range req.Bills {
		totalAmount += bill.TotalAmount
	}
	paymentDataReq := &providerEntity.PayBillDataRequest{
		RequestID:     req.TransactionID,
		CustomerCode:  req.CustomerID,
		ServiceCode:   billExtInfo.ServiceCode,
		ReferenceCode: billExtInfo.ReferenceCode,
		Amount:        totalAmount,
	}

	paymentDataResp, err := pro.PayBill(ctx, paymentDataReq)
	if err != nil {
		resp.ProviderReturnMessage = err.Error()
		return resp
	}

	resp.ErrorCode = constant.MapPaymentStatusCode(paymentDataResp.FinalStatus, req.Bills[0].ServiceID)
	resp.ProviderReturnCode = paymentDataResp.FinalStatus
	resp.ProviderReturnMessage = paymentDataResp.Message
	return resp
}

func NewService(providerCaller map[constant.ServiceID]provider.Provider, cacheSrv caching.Service, converterService business.ConverterStrategyFactory) Service {
	return &service{
		provider:         providerCaller,
		cacheSrv:         cacheSrv,
		converterService: converterService,
	}
}
func logErrorService(ctx context.Context, serviceID string) {
	logger := logging.FromContext(ctx)
	logger.Errorf("err service_id %s not supported", serviceID)
}
