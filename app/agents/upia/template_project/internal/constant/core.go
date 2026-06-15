package constant

const (
	// Exception return when query bill has exceptions
	Exception = 0
	// ProviderSuccess returns when query bill success
	ProviderSuccess = 1

	// ProviderUnavailable call to provider service fail cause connection
	// ex: timeout, service unavailable, connect fail,...
	ProviderUnavailable = -550

	// ProviderTimeout demonstrate when provider take too long to response
	ProviderTimeout = -551

	// ProviderCustomerMaybeWrong demonstrate when a customer maybe wrong because provider system doesn't know
	ProviderCustomerMaybeWrong = -552

	// ProviderBillEmpty demonstrate customer code correct but bill empty
	// this code equal Success but return empty bill list
	ProviderBillEmpty = -553

	// ProviderCustomerCodeNotExist demonstrate customer code absolutely non-existent
	// this code maybe cause user blocking
	ProviderCustomerCodeNotExist = -554

	// ProviderCustomerCodeManySupplier deprecated
	ProviderCustomerCodeManySupplier = -555

	// ProviderAPIFail call to provider service fail cause connection
	// ex: timeout, service unavailable, connect fail,...
	ProviderAPIFail = -556

	// ProviderSupplierInvalid call to provider service fail cause connection
	// ex: timeout, service unavailable, connect fail,...
	ProviderSupplierInvalid = -557

	// ProviderSupplierOrCustomerCodeInvalid deprecated
	ProviderSupplierOrCustomerCodeInvalid = -558

	// ProviderReturnFail using when provider return logical error
	// ex: parameters not valid, wrong sig, wrong checksum, ...
	ProviderReturnFail = -559

	// ProviderCustomerInfoNotExist deprecated
	ProviderCustomerInfoNotExist = -560

	// ProviderRedirect using for SCTV prepaid, redirect to SCTV postpaid if customer has outstanding SCTV postpaid
	ProviderRedirect = -570

	// ProviderBillDetailNotExist ???
	ProviderBillDetailNotExist = -561

	// ProviderReachLimitation returns when the request has over quota or insurance account empty
	ProviderReachLimitation = -562

	// ProviderShowCustomerMessage returns when we need show provider message
	ProviderShowCustomerMessage = -591

	// ProviderCustomerCodeNotExistOrNotSupportArea deprecated
	ProviderCustomerCodeNotExistOrNotSupportArea = -592

	// ProviderMaintenance returns when provider has not avalable in short duration
	ProviderMaintenance = -593

	// ProviderBillLocked returns when bill has been locked
	ProviderBillLocked = -594

	// ProviderCustomerCodeNotExistOrMaintenanceArea deprecated
	ProviderCustomerCodeNotExistOrMaintenanceArea = -595

	// ProviderErrorCodeNotDefined return when provider response a not defined error
	ProviderErrorCodeNotDefined = -599

	// ProviderContractPaidOff return when provider response contract is paid off
	ProviderContractPaidOff = -601

	ProviderInternalQuotaExceeded = -580
)

const (
	// DeliverProcessing return when service can get final status from provider and service **CAN** query final status. When core-api recieve DeliverProcessing status, it will call get deliver status API
	DeliverProcessing = 3
	// DeliverSuccess return when transaction delivery successful
	DeliverSuccess = 1
	// DeliverManualCheck return when service can get final status from provider and service **CAN NOT** query final status
	DeliverManualCheck   = -400
	DeliverFail          = -401
	WaitGetStatusDeliver = 7
)

const (
	// PaymentRuleUnknown return when error
	PaymentRuleUnknown = "0"

	// PaymentRuleAll indicates that user has to pay all the bills return in list
	PaymentRuleAll = "1"
	// PaymentRuleOldestBill indicates that user has to pay the first bill return in list
	PaymentRuleOldestBill = "2"
	// PaymentRuleAnyBill indicates that user can pay one bill in any position in list
	PaymentRuleAnyBill = "3"
	// PaymentRuleInputAmount indicates that user can input the number amount that will be call to provider
	PaymentRuleInputAmount = "5"
	// PaymentRuleContiguousBills indicates that user can can pay one or many bills begin from the first bill
	PaymentRuleContiguousBills = "6"
)
