package base

import (
	"encoding/json"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/constant"
)

type (
	GetBillDataRequest struct {
		UserID      string `json:"userid"`
		CustomerID  string `json:"customerid" validate:"required"`
		ServiceID   string `json:"serviceid" validate:"required"`
		ProviderID  string `json:"providerid" validate:"required"`
		PhoneNumber string `json:"phonenumber"`
		Internal    bool   `json:"internal"`
	}
	GetBillDataResponse struct {
		BaseDataResponse
		PaymentRule  string   `json:"paymentrule"`
		Bills        []Bill   `json:"bills"`
		ContractData Contract `json:"contractdata"`
		ExtData      string   `extdata`
	}

	Contract struct {
		Code    string `json:"code"`
		Name    string `json:"name"`
		Address string `json:"address"`
		Phone   string `json:"phone"`

		TotalDebt       int64  `json:"totaldebt"`
		IdentityNumber  string `json:"identitynumber"`
		LastBillToDate  string `json:"lastbilltodate"`
		ContractExtInfo string `json:"contractextinfo"`

		Detail string `json:"detail"`
		Type   string `json:"type"`
	}
)

type (
	PayBillDataRequest struct {
		CustomerID    string `json:"customerid" validate:"required"`
		TransactionID string `json:"transid" validate:"required" validate:"required"`
		Bills         []Bill `json:"bills" validate:"required"`
	}

	PayBillDataResponse struct {
		BaseDataResponse
		ProviderTransID string `json:"providertransid"`
		PayerName       string `json:"payername"`
	}
)

type (
	CheckTransactionDataRequest struct {
		TransactionId         string `json:"transid"`
		AppID                 int64  `json:"appid"`
		OrderID               int64  `json:"orderid"`
		ProviderTransactionID string `json:"providertransid" validate:"required"`
		ExInfo                string `json:"exinfo"`
	}

	CheckTransactionExInfo struct {
		Amount       int64  `json:"amount"`
		AppServiceID string `json:"appserviceid"`
		SupplierCode string `json:"suppliercode"`
		CustomerCode string `json:"customercode"`
		BillID       string `json:"billid"`
	}

	CheckTransactionDataResponse struct {
		BaseDataResponse
		ProviderData string `json:"providerdata"`
	}
)

type BaseDataResponse struct {
	ErrorCode             int    `json:"errorcode"`
	ProviderReturnCode    string `json:"providerreturncode"`
	ProviderReturnMessage string `json:"providerreturnmessage"`
}

type Bill struct {
	BillID       string `json:"billid"`
	Month        string `json:"month"`
	Year         string `json:"year"`
	TotalAmount  int64  `json:"moneyamount"`
	ExtAmount    string `json:"extamount"`
	PaymentFee   int64  `json:"paymentfee"`
	DueDate      string `json:"duedate"`
	BillType     int    `json:"billtype"`
	BillTypeDesc string `json:"pkg"`
	//
	ServiceID    string `json:"serviceid"`
	CustomerID   string `json:"customerid"`
	CustomerCode string `json:"customercode"`
	CustomerName string `json:"customername"`
	Address      string `json:"address"`
	Phone        string `json:"phone"`
	//
	ExInfo       string `json:"exinfo"`
	ZlpPaymentId string `json:"zlppaymentid"`
}

type ExtInfo struct {
	CustomerCode  string `json:"customercode"`
	CustomerName  string `json:"customername"`
	Address       string `json:"address"`
	TotalDebt     int64  `json:"totaldebt"`
	Data          string `json:"data,omitempty"`
	PaymentType   string `json:"type"`
	VAT           string `json:"vat"`
	Fee           string `json:"fee"`
	TotalVAT      string `json:"vatAmount"`
	TotalFee      string `json:"feeAmount"`
	TotalAmount   string `json:"totalAmount"`
	ReferenceCode string `json:"referencecode"`
	ServiceCode   string `json:"serviceid"`
}

type ExtData struct {
	Month     string `json:"month"`
	Amount    int64  `json:"amount"`
	MinAmount int32  `json:"minamount"`
	DueDate   string `json:"duedate"`
}

type BillCheck struct {
	Bill
	BankId     string `json:"bankid"`
	DateIssued string `json:"dateissued"`
}

type ExtAmount struct {
	MinInput int32 `json:"mininput"`
	MaxInput int64 `json:"maxinput"`

	Min     int32 `json:"min,omitempty"`
	Max     int64 `json:"max,omitempty"`
	Default int64 `json:"default"`
}

// SetExtInfo ...
func (b *Bill) SetExtInfo(ext *ExtInfo) {
	if ext == nil {
		return
	}
	byt, _ := json.Marshal(ext)
	b.ExInfo = string(byt)
}

func DefaultBaseDataResponse() BaseDataResponse {
	return BaseDataResponse{
		ErrorCode: constant.ProviderAPIFail,
	}
}
