package manager

import (
	baseEntity "gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/entity/base"
	providerEntity "gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/entity/provider"
)

//go:generate mockgen -destination=mocks/interface_mock.go -package=mocks -source=interface.go
type ConverterStrategy interface {
	GetPaymentRule() string
	ConvertBillEntity(serviceID string, providerId string, providerResp *providerEntity.GetBillDataResponse) []baseEntity.Bill
	GetContractType(srvID string) string
}
