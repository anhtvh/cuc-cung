package dto

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/constant"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/utils/jsonutils"
)

type (
	BaseRequest struct {
		ClientID  string `json:"clientid" form:"clientid" binding:"required"`
		Signature string `json:"sig" form:"sig" binding:"required"`
		DataJSON  string `json:"data" form:"data" binding:"required"`
		ReqDate   string `json:"reqdate" form:"reqdate"  binding:"required"`
	}

	BaseResponse struct {
		ReturnCode    int    `json:"returncode"`
		ReturnMessage string `json:"returnmessage"`
		Data          string `json:"data"`
	}
)

func (b *BaseResponse) DefaultResponse() {
	b.ReturnCode = constant.Exception
	b.ReturnMessage = "exception"
}

func (b *BaseResponse) ResponseSuccess(data interface{}) {
	b.ReturnCode = constant.ProviderSuccess
	b.ReturnMessage = "Success"
	b.Data = jsonutils.ToJSONString(data)
}

func (br BaseRequest) GetClientID() string {
	return br.ClientID
}

func (br BaseRequest) DeserializeData(out interface{}) error {
	if err := json.Unmarshal([]byte(br.DataJSON), out); err != nil {
		return err
	}
	return nil
}

func (br BaseRequest) ValidateSig(key string) bool {
	sigData := strings.Join([]string{br.DataJSON, br.ReqDate, key}, "|")
	hash := sha256.New()
	_, _ = hash.Write([]byte(sigData))
	ourSig := hex.EncodeToString(hash.Sum(nil))
	return ourSig == br.Signature
}
