package business

import (
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/business/manager"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/constant"
)

//go:generate mockgen -destination=mocks/base_mock.go -package=mocks -source=base.go
type ConverterStrategyFactory interface {
	GetConverterStrategy(serviceID constant.ServiceID) manager.ConverterStrategy
}

type converterStrategyFactory struct {
	converterMap map[constant.ServiceID]manager.ConverterStrategy
}

func (b *converterStrategyFactory) GetConverterStrategy(serviceID constant.ServiceID) manager.ConverterStrategy {
	return b.converterMap[serviceID]
}

func NewConverterStrategyFactory(converterMap map[constant.ServiceID]manager.ConverterStrategy) ConverterStrategyFactory {
	return &converterStrategyFactory{
		converterMap: converterMap,
	}
}
